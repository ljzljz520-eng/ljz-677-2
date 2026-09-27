"""清单导入与校验"""
import csv
import io
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import PaymentRecord, RecordStatus, Task, TaskStatus, Unit
from ..validators import (
    validate_amount,
    validate_id_card,
    validate_month,
    validate_name,
    validate_unit_code,
)

HEADER_MAP = {
    "身份证号": "id_card", "id_card": "id_card",
    "姓名": "name", "name": "name",
    "缴费月份": "month", "month": "month",
    "缴费金额": "amount", "amount": "amount",
    "单位编号": "unit_code", "unit_code": "unit_code",
}
REQUIRED_FIELDS = ["id_card", "name", "month", "amount", "unit_code"]
MAX_ROWS = 200_000
COMMIT_EVERY = 1000


def parse_csv(content: bytes) -> list[dict]:
    """解析 CSV（自动识别 UTF-8/GBK，支持中英文表头），返回行字典列表"""
    text = None
    for enc in ("utf-8-sig", "gbk"):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("文件编码无法识别（仅支持 UTF-8 / GBK）")

    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any((c or "").strip() for c in r)]
    if not rows:
        raise ValueError("文件内容为空")

    header = [h.strip() for h in rows[0]]
    col_idx: dict[str, int] = {}
    for i, h in enumerate(header):
        key = HEADER_MAP.get(h) or HEADER_MAP.get(h.lower())
        if key and key not in col_idx:
            col_idx[key] = i
    missing = [k for k in REQUIRED_FIELDS if k not in col_idx]
    if missing:
        raise ValueError(
            "缺少必需列：" + ",".join(missing)
            + "（支持表头：身份证号/姓名/缴费月份/缴费金额/单位编号）"
        )

    data_rows = rows[1:]
    if not data_rows:
        raise ValueError("文件中没有数据行")
    if len(data_rows) > MAX_ROWS:
        raise ValueError(f"单任务最多支持 {MAX_ROWS} 行，实际 {len(data_rows)} 行")

    result = []
    for line_no, r in enumerate(data_rows, start=2):
        def cell(field: str) -> str:
            i = col_idx[field]
            return r[i].strip() if i < len(r) else ""

        result.append({
            "row_no": line_no,
            "id_card": cell("id_card").upper(),
            "name": cell("name"),
            "month": cell("month"),
            "amount": cell("amount"),
            "unit_code": cell("unit_code"),
        })
    return result


def create_task_with_records(db: Session, filename: str, rows: list[dict]) -> Task:
    """创建导入任务并批量写入记录"""
    task_no = "T" + datetime.now().strftime("%Y%m%d%H%M%S") + uuid4hex()
    task = Task(task_no=task_no, filename=filename or "upload.csv",
                status=TaskStatus.PENDING, total_count=len(rows))
    db.add(task)
    db.flush()

    objs = [
        PaymentRecord(
            task_id=task.id,
            row_no=row["row_no"],
            id_card=row["id_card"],
            name=row["name"],
            month=row["month"],
            amount_raw=row["amount"],
            unit_code=row["unit_code"],
            status=RecordStatus.PENDING,
        )
        for row in rows
    ]
    db.bulk_save_objects(objs)
    db.commit()
    db.refresh(task)
    return task


def uuid4hex() -> str:
    return uuid.uuid4().hex[:6].upper()


def validate_task(db: Session, task_id: int) -> Task:
    """逐条校验任务内记录：身份证/姓名/月份/金额/单位编号/任务内查重"""
    task = db.get(Task, task_id)
    if task is None:
        raise ValueError(f"任务不存在: {task_id}")
    task.status = TaskStatus.VALIDATING
    db.commit()

    valid_unit_codes = {u.unit_code for u in db.query(Unit).all()}
    records = (
        db.query(PaymentRecord)
        .filter(PaymentRecord.task_id == task.id)
        .order_by(PaymentRecord.row_no)
        .all()
    )

    seen: set[tuple[str, str]] = set()  # (身份证号, 月份) 任务内查重
    valid_count = 0
    for i, rec in enumerate(records):
        errors: list[str] = []

        ok, msg = validate_id_card(rec.id_card)
        if not ok:
            errors.append(msg)
        ok, msg = validate_name(rec.name)
        if not ok:
            errors.append(msg)
        ok, msg = validate_month(rec.month)
        if not ok:
            errors.append(msg)
        ok, msg, amount = validate_amount(rec.amount_raw)
        if ok:
            rec.amount = amount
        else:
            errors.append(msg)
        ok, msg = validate_unit_code(rec.unit_code, valid_unit_codes)
        if not ok:
            errors.append(msg)

        dup_key = (rec.id_card, rec.month)
        if dup_key in seen:
            errors.append("任务内重复：同一身份证号同一月份出现多次")
        else:
            seen.add(dup_key)

        if errors:
            rec.status = RecordStatus.INVALID
            rec.error_msg = "；".join(errors)
        else:
            rec.status = RecordStatus.VALID
            rec.error_msg = None
            valid_count += 1

        if (i + 1) % COMMIT_EVERY == 0:
            db.commit()
    db.commit()

    task.valid_count = valid_count
    task.invalid_count = len(records) - valid_count
    task.status = TaskStatus.VALIDATED
    db.commit()
    db.refresh(task)
    return task
