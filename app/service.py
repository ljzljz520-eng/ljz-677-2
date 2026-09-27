# -*- coding: utf-8 -*-
"""业务逻辑: 导入 -> 校验 -> 分批上送 -> 结果回写 -> 重试 -> 错误明细"""
import csv
import io
import threading
from concurrent.futures import ThreadPoolExecutor

import config
import db
import platform_client
import validator

# 表头映射: 支持中文/英文列名
HEADER_MAP = {
    "姓名": "person_name", "name": "person_name",
    "身份证号": "id_card", "身份证": "id_card", "id_card": "id_card",
    "缴费月份": "month", "月份": "month", "month": "month",
    "缴费金额": "amount", "金额": "amount", "amount": "amount",
    "单位编号": "unit_code", "单位": "unit_code", "unit_code": "unit_code",
}
REQUIRED_COLS = ["person_name", "id_card", "month", "amount", "unit_code"]

_task_locks = {}
_task_locks_guard = threading.Lock()


def _task_lock(task_id):
    with _task_locks_guard:
        return _task_locks.setdefault(task_id, threading.Lock())


# ---------------- 1. 导入 ----------------

def import_task(name, filename, file_bytes):
    """解析CSV并创建任务与明细记录"""
    text = file_bytes.decode("utf-8-sig", "replace")
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any((c or "").strip() for c in r)]
    if not rows:
        raise ValueError("文件为空或无有效数据行")

    header = [h.strip().lstrip("﻿") for h in rows[0]]
    col_idx = {}
    for i, h in enumerate(header):
        key = HEADER_MAP.get(h) or HEADER_MAP.get(h.lower())
        if key and key not in col_idx:
            col_idx[key] = i
    missing = [c for c in REQUIRED_COLS if c not in col_idx]
    if missing:
        raise ValueError("缺少必需列: %s (支持表头: 姓名/身份证号/缴费月份/缴费金额/单位编号)"
                         % ",".join(missing))

    records = []
    for row_no, row in enumerate(rows[1:], start=2):
        def cell(col):
            i = col_idx[col]
            return row[i].strip() if i < len(row) else ""
        records.append((row_no, cell("person_name"), cell("id_card"),
                        cell("month"), cell("amount"), cell("unit_code")))
    if not records:
        raise ValueError("文件中没有数据行")
    if len(records) > 200000:
        raise ValueError("单任务最多支持20万条记录")

    ts = db.now()
    task_id = db.execute(
        "INSERT INTO tasks(name, filename, status, total_count, created_at, updated_at)"
        " VALUES(?,?,?,?,?,?)",
        (name or filename, filename, "IMPORTED", len(records), ts, ts))
    db.execute_many(
        "INSERT INTO records(task_id, row_no, person_name, id_card, month, amount,"
        " unit_code, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        [(task_id, r[0], r[1], r[2], r[3], r[4], r[5], ts, ts) for r in records])
    return task_id


# ---------------- 2. 校验 ----------------

def validate_task(task_id):
    task = _must_task(task_id)
    if task["status"] not in ("IMPORTED", "VALIDATED"):
        raise ValueError("当前状态[%s]不允许重新校验" % task["status"])
    with _task_lock(task_id):
        known = {u["unit_code"] for u in db.query_all("SELECT unit_code FROM units")}
        rows = db.query_all("SELECT id, person_name, id_card, month, amount, unit_code"
                            " FROM records WHERE task_id=?", (task_id,))
        ts = db.now()
        updates, valid, invalid = [], 0, 0
        for r in rows:
            errs = validator.validate_record(r, known)
            if errs:
                invalid += 1
                updates.append(("INVALID", "; ".join(errs), "NONE", ts, r["id"]))
            else:
                valid += 1
                updates.append(("VALID", None, "PENDING", ts, r["id"]))
        db.execute_many(
            "UPDATE records SET validate_status=?, validate_error=?, submit_status=?,"
            " updated_at=? WHERE id=?", updates)
        db.execute(
            "UPDATE tasks SET status='VALIDATED', valid_count=?, invalid_count=?,"
            " updated_at=? WHERE id=?", (valid, invalid, ts, task_id))
    return {"valid": valid, "invalid": invalid}


# ---------------- 3. 分批上送 ----------------

def submit_task(task_id):
    task = _must_task(task_id)
    if task["status"] != "VALIDATED":
        raise ValueError("任务须先完成校验才能上送(当前状态:%s)" % task["status"])
    with _task_lock(task_id):
        pending = db.query_all(
            "SELECT COUNT(*) c FROM batches WHERE task_id=? AND status IN ('PENDING','SUBMITTING')",
            (task_id,))[0]["c"]
        if pending:
            raise ValueError("该任务存在正在上送的批次, 请等待完成")
        recs = db.query_all(
            "SELECT id FROM records WHERE task_id=? AND validate_status='VALID'"
            " AND submit_status='PENDING' ORDER BY id", (task_id,))
        if not recs:
            raise ValueError("没有待上送的有效记录")

        ts = db.now()
        old = db.query_one("SELECT COALESCE(MAX(batch_no),0) m FROM batches WHERE task_id=?",
                           (task_id,))["m"]
        batch_ids = []
        for i in range(0, len(recs), config.BATCH_SIZE):
            chunk = recs[i:i + config.BATCH_SIZE]
            bid = db.execute(
                "INSERT INTO batches(task_id, batch_no, record_count, status, created_at, updated_at)"
                " VALUES(?,?,?,?,?,?)",
                (task_id, old + i // config.BATCH_SIZE + 1, len(chunk), "PENDING", ts, ts))
            db.execute_many("UPDATE records SET batch_id=?, updated_at=? WHERE id=?",
                            [(bid, ts, r["id"]) for r in chunk])
            batch_ids.append(bid)
        db.execute("UPDATE tasks SET status='SUBMITTING', batch_count=batch_count+?, updated_at=?"
                   " WHERE id=?", (len(batch_ids), ts, task_id))

    threading.Thread(target=_run_batches, args=(task_id, batch_ids), daemon=True).start()
    return {"batches": len(batch_ids), "records": len(recs)}


def _run_batches(task_id, batch_ids):
    """后台线程: 并发上送各批次, 全部结束后回写任务汇总"""
    with ThreadPoolExecutor(max_workers=config.SUBMIT_WORKERS) as pool:
        list(pool.map(process_batch, batch_ids))
    _refresh_task(task_id)
    db.execute("UPDATE tasks SET status='DONE', updated_at=? WHERE id=?", (db.now(), task_id))


def process_batch(batch_id):
    """上送单个批次并回写结果(供首次上送与重试共用)"""
    batch = db.query_one("SELECT * FROM batches WHERE id=?", (batch_id,))
    if not batch:
        return
    ts = db.now()
    db.execute("UPDATE batches SET status='SUBMITTING', submitted_at=?, error_message=NULL,"
               " updated_at=? WHERE id=?", (ts, ts, batch_id))
    recs = db.query_all(
        "SELECT id, row_no, person_name, id_card, month, amount, unit_code FROM records"
        " WHERE batch_id=? AND submit_status!='SUCCESS' ORDER BY row_no", (batch_id,))
    try:
        resp = platform_client.submit_batch(batch_id, recs)
    except platform_client.PlatformTimeout as e:
        db.execute("UPDATE batches SET status='TIMEOUT', error_message=?, updated_at=? WHERE id=?",
                   (str(e), db.now(), batch_id))
        _refresh_task(batch["task_id"])
        return
    except platform_client.PlatformError as e:
        db.execute("UPDATE batches SET status='FAILED', error_message=?, updated_at=? WHERE id=?",
                   (str(e), db.now(), batch_id))
        _refresh_task(batch["task_id"])
        return
    except Exception as e:  # 兜底, 保证后台线程不静默崩溃
        db.execute("UPDATE batches SET status='FAILED', error_message=?, updated_at=? WHERE id=?",
                   ("系统异常: %s" % e, db.now(), batch_id))
        _refresh_task(batch["task_id"])
        return

    results = {r["row_no"]: r for r in resp.get("results", [])}
    ts = db.now()
    updates, succ, fail = [], 0, 0
    for r in recs:
        res = results.get(r["row_no"])
        if res and res.get("success"):
            succ += 1
            updates.append(("SUCCESS", None, ts, r["id"]))
        else:
            fail += 1
            reason = (res or {}).get("error") or "平台未返回该记录结果"
            updates.append(("FAILED", reason, ts, r["id"]))
    db.execute_many("UPDATE records SET submit_status=?, submit_error=?, updated_at=? WHERE id=?",
                    updates)
    status = "SUCCESS" if fail == 0 else ("FAILED" if succ == 0 else "PARTIAL")
    db.execute(
        "UPDATE batches SET status=?, platform_batch_id=?, success_count=?, failed_count=?,"
        " error_message=?, finished_at=?, updated_at=? WHERE id=?",
        (status, resp.get("platform_batch_id"), succ, fail,
         None if fail == 0 else "%d条记录被平台拒绝" % fail, ts, ts, batch_id))
    _refresh_task(batch["task_id"])


# ---------------- 4. 重试超时/失败批次 ----------------

def retry_batch(batch_id):
    batch = db.query_one("SELECT * FROM batches WHERE id=?", (batch_id,))
    if not batch:
        raise ValueError("批次不存在")
    if batch["status"] not in ("TIMEOUT", "FAILED"):
        raise ValueError("仅超时或失败的批次可重试(当前:%s)" % batch["status"])
    if batch["retry_count"] >= config.MAX_RETRY:
        raise ValueError("已达最大重试次数(%d)" % config.MAX_RETRY)
    db.execute("UPDATE batches SET retry_count=retry_count+1, status='PENDING', updated_at=?"
               " WHERE id=?", (db.now(), batch_id))
    threading.Thread(target=process_batch, args=(batch_id,), daemon=True).start()
    return {"retry_count": batch["retry_count"] + 1}


# ---------------- 5. 错误明细下载 ----------------

def error_csv(task_id):
    _must_task(task_id)
    rows = db.query_all(
        "SELECT row_no, person_name, id_card, month, amount, unit_code,"
        " validate_status, validate_error, submit_status, submit_error"
        " FROM records WHERE task_id=? AND (validate_status='INVALID' OR submit_status='FAILED')"
        " ORDER BY row_no", (task_id,))
    buf = io.StringIO()
    buf.write("﻿")  # BOM, Excel 兼容
    w = csv.writer(buf)
    w.writerow(["错误类型", "行号", "姓名", "身份证号", "缴费月份", "缴费金额", "单位编号", "错误原因"])
    for r in rows:
        if r["validate_status"] == "INVALID":
            w.writerow(["校验失败", r["row_no"], r["person_name"], r["id_card"], r["month"],
                        r["amount"], r["unit_code"], r["validate_error"]])
        if r["submit_status"] == "FAILED":
            w.writerow(["上送失败", r["row_no"], r["person_name"], r["id_card"], r["month"],
                        r["amount"], r["unit_code"], r["submit_error"]])
    return buf.getvalue()


# ---------------- 查询与汇总 ----------------

def _refresh_task(task_id):
    """任务级汇总回写: 成功/失败/超时批次数"""
    db.execute(
        "UPDATE tasks SET"
        " success_count=(SELECT COUNT(*) FROM records WHERE task_id=? AND submit_status='SUCCESS'),"
        " failed_count=(SELECT COUNT(*) FROM records WHERE task_id=? AND submit_status='FAILED'),"
        " timeout_batches=(SELECT COUNT(*) FROM batches WHERE task_id=? AND status='TIMEOUT'),"
        " updated_at=? WHERE id=?",
        (task_id, task_id, task_id, db.now(), task_id))


def _must_task(task_id):
    task = db.query_one("SELECT * FROM tasks WHERE id=?", (task_id,))
    if not task:
        raise ValueError("任务不存在")
    return task
