"""任务相关 API：上传、校验、提交、查询、重试、错误明细下载"""
import csv
import io
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..models import (
    RETRYABLE_BATCH_STATUS,
    Batch,
    PaymentRecord,
    RecordStatus,
    Task,
    TaskStatus,
)
from ..services import import_service, submit_service

router = APIRouter(tags=["tasks"])

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


# ---------- 序列化 ----------

def task_to_dict(t: Task) -> dict:
    return {
        "id": t.id,
        "task_no": t.task_no,
        "filename": t.filename,
        "status": t.status,
        "total_count": t.total_count,
        "valid_count": t.valid_count,
        "invalid_count": t.invalid_count,
        "success_count": t.success_count,
        "failed_count": t.failed_count,
        "timeout_count": t.timeout_count,
        "error_message": t.error_message,
        "created_at": t.created_at.strftime("%Y-%m-%d %H:%M:%S") if t.created_at else None,
        "updated_at": t.updated_at.strftime("%Y-%m-%d %H:%M:%S") if t.updated_at else None,
    }


def record_to_dict(r: PaymentRecord) -> dict:
    return {
        "id": r.id,
        "row_no": r.row_no,
        "id_card": r.id_card,
        "name": r.name,
        "month": r.month,
        "amount": str(r.amount) if r.amount is not None else r.amount_raw,
        "unit_code": r.unit_code,
        "status": r.status,
        "error_msg": r.error_msg,
        "batch_id": r.batch_id,
    }


def batch_to_dict(b: Batch) -> dict:
    return {
        "id": b.id,
        "batch_no": b.batch_no,
        "status": b.status,
        "record_count": b.record_count,
        "success_count": b.success_count,
        "failed_count": b.failed_count,
        "retry_count": b.retry_count,
        "error_msg": b.error_msg,
        "retryable": b.status in RETRYABLE_BATCH_STATUS,
        "submitted_at": b.submitted_at.strftime("%Y-%m-%d %H:%M:%S") if b.submitted_at else None,
        "finished_at": b.finished_at.strftime("%Y-%m-%d %H:%M:%S") if b.finished_at else None,
    }


# ---------- 后台协程 ----------

async def _run_validate(task_id: int):
    db = SessionLocal()
    try:
        import_service.validate_task(db, task_id)
    except Exception as exc:
        db.rollback()
        task = db.get(Task, task_id)
        if task:
            task.status = TaskStatus.FAILED
            task.error_message = f"校验过程异常：{exc}"[:500]
            db.commit()
    finally:
        db.close()


# ---------- 接口 ----------

@router.post("/tasks/upload")
async def upload_task(request: Request, file: UploadFile, db: Session = Depends(get_db)):
    """上传缴费清单 CSV，创建任务并自动触发校验"""
    content = await file.read()
    if not content:
        raise HTTPException(400, "文件为空")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, "文件超过 50MB 限制")
    try:
        rows = import_service.parse_csv(content)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    task = import_service.create_task_with_records(db, file.filename, rows)
    await request.app.state.runner.run(_run_validate(task.id))
    db.expire_all()
    return task_to_dict(db.get(Task, task.id))


@router.get("/tasks")
def list_tasks(status: str = "", page: int = 1, size: int = 20, db: Session = Depends(get_db)):
    q = db.query(Task)
    if status:
        q = q.filter(Task.status == status)
    total = q.count()
    items = q.order_by(Task.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"total": total, "items": [task_to_dict(t) for t in items]}


@router.get("/tasks/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task_to_dict(task)


@router.get("/tasks/{task_id}/records")
def list_records(
    task_id: int,
    status: str = "",
    page: int = 1,
    size: int = 50,
    db: Session = Depends(get_db),
):
    if not db.get(Task, task_id):
        raise HTTPException(404, "任务不存在")
    q = db.query(PaymentRecord).filter(PaymentRecord.task_id == task_id)
    if status:
        q = q.filter(PaymentRecord.status == status)
    total = q.count()
    items = (
        q.order_by(PaymentRecord.row_no)
        .offset((page - 1) * size)
        .limit(min(size, 500))
        .all()
    )
    return {"total": total, "items": [record_to_dict(r) for r in items]}


@router.get("/tasks/{task_id}/batches")
def list_batches(task_id: int, db: Session = Depends(get_db)):
    if not db.get(Task, task_id):
        raise HTTPException(404, "任务不存在")
    batches = (
        db.query(Batch).filter(Batch.task_id == task_id).order_by(Batch.id).all()
    )
    return {"total": len(batches), "items": [batch_to_dict(b) for b in batches]}


@router.post("/tasks/{task_id}/submit")
async def submit_task_api(task_id: int, request: Request, db: Session = Depends(get_db)):
    """触发分批提交（后台异步执行）"""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if task.status == TaskStatus.SUBMITTING:
        raise HTTPException(409, "任务正在提交中，请勿重复操作")
    if task.status != TaskStatus.VALIDATED:
        raise HTTPException(409, f"任务状态为 {task.status}，仅校验完成的任务可提交")
    if task.valid_count == 0:
        raise HTTPException(409, "任务没有校验通过的记录，无法提交")

    client = request.app.state.external_client
    await request.app.state.runner.run(
        submit_service.submit_task(task_id, client)
    )
    db.expire_all()
    return task_to_dict(db.get(Task, task_id))


@router.post("/batches/{batch_id}/retry")
async def retry_batch_api(batch_id: int, request: Request, db: Session = Depends(get_db)):
    """重试超时/失败批次"""
    batch = db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(404, "批次不存在")
    if batch.status not in RETRYABLE_BATCH_STATUS:
        raise HTTPException(409, f"批次状态为 {batch.status}，仅超时/失败批次可重试")

    client = request.app.state.external_client
    try:
        await request.app.state.runner.run(
            submit_service.retry_batch(batch_id, client)
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    db.expire_all()
    return batch_to_dict(db.get(Batch, batch_id))


ERROR_TYPE_MAP = {
    RecordStatus.INVALID: "校验错误",
    RecordStatus.FAILED: "提交失败",
    RecordStatus.TIMEOUT: "提交超时",
}


@router.get("/tasks/{task_id}/errors/download")
def download_errors(task_id: int, db: Session = Depends(get_db)):
    """下载错误明细 CSV（校验错误 + 提交失败 + 提交超时）"""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    records = (
        db.query(PaymentRecord)
        .filter(
            PaymentRecord.task_id == task_id,
            PaymentRecord.status.in_(
                [RecordStatus.INVALID, RecordStatus.FAILED, RecordStatus.TIMEOUT]
            ),
        )
        .order_by(PaymentRecord.row_no)
        .all()
    )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["行号", "身份证号", "姓名", "缴费月份", "缴费金额", "单位编号", "错误类型", "错误信息"])
    for r in records:
        writer.writerow([
            r.row_no, r.id_card, r.name, r.month,
            str(r.amount) if r.amount is not None else r.amount_raw,
            r.unit_code, ERROR_TYPE_MAP.get(r.status, r.status), r.error_msg or "",
        ])

    content = "﻿" + buf.getvalue()  # BOM，Excel 直接打开不乱码
    filename = quote(f"errors_{task.task_no}.csv")
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get("/sample-csv")
def sample_csv():
    """下载 CSV 模板"""
    content = (
        "﻿身份证号,姓名,缴费月份,缴费金额,单位编号\n"
        "11010119900307791X,张三,2026-08,1500.00,1101010001\n"
        "310104198505124321,李四,2026-08,2360.50,3101040003\n"
    )
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''sample.csv"},
    )
