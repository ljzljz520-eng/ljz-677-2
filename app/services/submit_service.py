"""分批提交与重试"""
import asyncio
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session, sessionmaker

from ..database import SessionLocal
from ..models import (
    RETRYABLE_BATCH_STATUS,
    RETRYABLE_RECORD_STATUS,
    Batch,
    BatchStatus,
    PaymentRecord,
    RecordStatus,
    Task,
    TaskStatus,
)
from .external_client import BatchTimeoutError

DEFAULT_BATCH_SIZE = 100        # 每批记录数
DEFAULT_EXTERNAL_TIMEOUT = 10.0  # 调用外部平台超时（秒）
DEFAULT_CONCURRENCY = 3          # 同时提交的批次数


def refresh_task_stats(db: Session, task: Task) -> None:
    """根据记录状态重算任务统计"""
    rows = (
        db.query(PaymentRecord.status, func.count())
        .filter(PaymentRecord.task_id == task.id)
        .group_by(PaymentRecord.status)
        .all()
    )
    counts = {s: n for s, n in rows}
    task.total_count = sum(counts.values())
    task.invalid_count = counts.get(RecordStatus.INVALID, 0)
    task.valid_count = task.total_count - task.invalid_count
    task.success_count = counts.get(RecordStatus.SUCCESS, 0)
    task.failed_count = counts.get(RecordStatus.FAILED, 0)
    task.timeout_count = counts.get(RecordStatus.TIMEOUT, 0)


def _build_payload(batch: Batch, records: list[PaymentRecord]) -> list[dict]:
    return [
        {
            "row_ref": r.id,
            "id_card": r.id_card,
            "name": r.name,
            "month": r.month,
            "amount": str(r.amount),
            "unit_code": r.unit_code,
            # 幂等键：批次号+记录ID，重试时外部平台去重，避免重复入账
            "idempotency_key": f"{batch.batch_no}:{r.id}",
        }
        for r in records
    ]


async def _submit_one_batch(
    db: Session,
    batch: Batch,
    client,
    timeout: float,
    record_statuses: set,
) -> None:
    """提交单个批次并回写结果（成功/失败/超时）"""
    records = (
        db.query(PaymentRecord)
        .filter(
            PaymentRecord.batch_id == batch.id,
            PaymentRecord.status.in_(record_statuses),
        )
        .order_by(PaymentRecord.row_no)
        .all()
    )
    if not records:
        batch.status = BatchStatus.SUCCESS
        batch.finished_at = datetime.now()
        db.commit()
        return

    batch.status = BatchStatus.SUBMITTING
    batch.submitted_at = datetime.now()
    batch.error_msg = None
    for r in records:
        r.status = RecordStatus.SUBMITTING
        r.error_msg = None
    db.commit()

    payload = _build_payload(batch, records)
    try:
        results = await asyncio.wait_for(
            client.submit_batch(batch.batch_no, payload), timeout=timeout
        )
    except (BatchTimeoutError, asyncio.TimeoutError):
        # 整批超时：批次与记录置为 TIMEOUT，等待经办人重试
        batch.status = BatchStatus.TIMEOUT
        batch.error_msg = "批次提交超时，可重试"
        batch.finished_at = datetime.now()
        for r in records:
            r.status = RecordStatus.TIMEOUT
            r.error_msg = "批次提交超时，待重试"
        db.commit()
        return
    except Exception as exc:  # 外部平台不可用等异常
        batch.status = BatchStatus.FAILED
        batch.error_msg = f"批次提交异常：{exc}"[:500]
        batch.finished_at = datetime.now()
        for r in records:
            r.status = RecordStatus.FAILED
            r.error_msg = "批次提交异常，可重试"
        db.commit()
        return

    # 逐条回写外部平台处理结果
    result_map = {res["row_ref"]: res for res in results}
    success_count = 0
    failed_count = 0
    for r in records:
        res = result_map.get(r.id)
        if res is None:
            r.status = RecordStatus.FAILED
            r.error_msg = "外部平台未返回该记录的处理结果"
            failed_count += 1
        elif res.get("success"):
            r.status = RecordStatus.SUCCESS
            r.error_msg = None
            success_count += 1
        else:
            r.status = RecordStatus.FAILED
            r.error_msg = res.get("error") or "外部平台处理失败"
            failed_count += 1

    batch.success_count = success_count
    batch.failed_count = failed_count
    batch.finished_at = datetime.now()
    if failed_count == 0:
        batch.status = BatchStatus.SUCCESS
    elif success_count == 0:
        batch.status = BatchStatus.FAILED
        batch.error_msg = "批内全部记录被外部平台拒绝"
    else:
        batch.status = BatchStatus.PARTIAL_FAILED
    db.commit()


async def submit_task(
    task_id: int,
    client,
    session_factory: sessionmaker = SessionLocal,
    batch_size: int = DEFAULT_BATCH_SIZE,
    timeout: float = DEFAULT_EXTERNAL_TIMEOUT,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> None:
    """将任务内校验通过的记录分批提交到外部平台"""
    db = session_factory()
    try:
        task = db.get(Task, task_id)
        if task is None:
            return
        valid_records = (
            db.query(PaymentRecord)
            .filter(
                PaymentRecord.task_id == task.id,
                PaymentRecord.status == RecordStatus.VALID,
            )
            .order_by(PaymentRecord.row_no)
            .all()
        )
        if not valid_records:
            task.status = TaskStatus.COMPLETED
            db.commit()
            return

        task.status = TaskStatus.SUBMITTING
        db.commit()

        # 分批
        existing = db.query(func.count(Batch.id)).filter(Batch.task_id == task.id).scalar() or 0
        batches: list[Batch] = []
        for i in range(0, len(valid_records), batch_size):
            chunk = valid_records[i:i + batch_size]
            seq = existing + 1 + i // batch_size
            batch = Batch(
                task_id=task.id,
                batch_no=f"{task.task_no}-B{seq:03d}",
                status=BatchStatus.PENDING,
                record_count=len(chunk),
            )
            db.add(batch)
            db.flush()
            for r in chunk:
                r.batch_id = batch.id
            batches.append(batch)
        db.commit()
        batch_ids = [b.id for b in batches]
    finally:
        db.close()

    # 并发提交（信号量限流），每个批次使用独立会话
    sem = asyncio.Semaphore(concurrency)

    async def worker(batch_id: int):
        async with sem:
            wdb = session_factory()
            try:
                b = wdb.get(Batch, batch_id)
                await _submit_one_batch(
                    wdb, b, client, timeout,
                    {RecordStatus.VALID, RecordStatus.SUBMITTING},
                )
                t = wdb.get(Task, task_id)
                refresh_task_stats(wdb, t)
                wdb.commit()
            finally:
                wdb.close()

    await asyncio.gather(*[worker(bid) for bid in batch_ids])

    db = session_factory()
    try:
        task = db.get(Task, task_id)
        refresh_task_stats(db, task)
        task.status = TaskStatus.COMPLETED
        db.commit()
    finally:
        db.close()


async def retry_batch(
    batch_id: int,
    client,
    session_factory: sessionmaker = SessionLocal,
    timeout: float = DEFAULT_EXTERNAL_TIMEOUT,
) -> Batch:
    """重试超时/失败批次：仅重新提交批内未成功的记录"""
    db = session_factory()
    try:
        batch = db.get(Batch, batch_id)
        if batch is None:
            raise ValueError(f"批次不存在: {batch_id}")
        if batch.status not in RETRYABLE_BATCH_STATUS:
            raise ValueError(f"批次状态为 {batch.status}，仅超时/失败批次可重试")

        batch.retry_count += 1
        db.commit()

        await _submit_one_batch(
            db, batch, client, timeout,
            RETRYABLE_RECORD_STATUS | {RecordStatus.SUBMITTING},
        )

        task = db.get(Task, batch.task_id)
        refresh_task_stats(db, task)
        db.commit()
        db.refresh(batch)
        return batch
    finally:
        db.close()
