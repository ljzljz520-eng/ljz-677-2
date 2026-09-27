"""数据模型：任务 / 缴费记录 / 批次 / 单位"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class TaskStatus:
    PENDING = "PENDING"          # 已导入，待校验
    VALIDATING = "VALIDATING"    # 校验中
    VALIDATED = "VALIDATED"      # 校验完成，待提交
    SUBMITTING = "SUBMITTING"    # 分批提交中
    COMPLETED = "COMPLETED"      # 全部批次处理完毕（可能含失败记录）
    FAILED = "FAILED"            # 任务失败（如文件解析错误）


class RecordStatus:
    PENDING = "PENDING"          # 待校验
    VALID = "VALID"              # 校验通过，待提交
    INVALID = "INVALID"          # 校验失败
    SUBMITTING = "SUBMITTING"    # 提交中
    SUCCESS = "SUCCESS"          # 外部平台受理成功
    FAILED = "FAILED"            # 外部平台拒绝
    TIMEOUT = "TIMEOUT"          # 批次超时，可重试


class BatchStatus:
    PENDING = "PENDING"
    SUBMITTING = "SUBMITTING"
    SUCCESS = "SUCCESS"          # 批内全部成功
    PARTIAL_FAILED = "PARTIAL_FAILED"  # 部分失败
    FAILED = "FAILED"            # 全部失败或调用异常
    TIMEOUT = "TIMEOUT"          # 超时，可重试


# 可重试的批次状态
RETRYABLE_BATCH_STATUS = {BatchStatus.TIMEOUT, BatchStatus.FAILED, BatchStatus.PARTIAL_FAILED}
# 重试时重新提交的记录状态
RETRYABLE_RECORD_STATUS = {RecordStatus.TIMEOUT, RecordStatus.FAILED}


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default=TaskStatus.PENDING, index=True)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    valid_count: Mapped[int] = mapped_column(Integer, default=0)
    invalid_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    timeout_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    records: Mapped[list["PaymentRecord"]] = relationship(
        back_populates="task", cascade="all, delete-orphan")
    batches: Mapped[list["Batch"]] = relationship(
        back_populates="task", cascade="all, delete-orphan")


class PaymentRecord(Base):
    __tablename__ = "payment_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    row_no: Mapped[int] = mapped_column(Integer)          # 源文件行号（含表头）
    id_card: Mapped[str] = mapped_column(String(18), index=True)
    name: Mapped[str] = mapped_column(String(64))
    month: Mapped[str] = mapped_column(String(7))         # YYYY-MM
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    amount_raw: Mapped[str] = mapped_column(String(32), default="")  # 原始金额文本
    unit_code: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(20), default=RecordStatus.PENDING, index=True)
    error_msg: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    batch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("batches.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    task: Mapped[Task] = relationship(back_populates="records")


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    batch_no: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default=BatchStatus.PENDING, index=True)
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_msg: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    task: Mapped[Task] = relationship(back_populates="batches")


class Unit(Base):
    __tablename__ = "units"

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    unit_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
