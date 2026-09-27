"""分批提交、超时、重试、错误明细下载测试"""
from app.main import app
from app.models import (
    Batch,
    BatchStatus,
    PaymentRecord,
    RecordStatus,
    TaskStatus,
)
from app.database import SessionLocal
from app.services.external_client import SimulatedExternalClient


def upload(client, content: bytes):
    return client.post("/api/tasks/upload", files={"file": ("t.csv", content, "text/csv")}).json()


def get_valid_id_cards(task_id):
    db = SessionLocal()
    try:
        return [r.id_card for r in db.query(PaymentRecord).filter(
            PaymentRecord.task_id == task_id,
            PaymentRecord.status == RecordStatus.VALID).all()]
    finally:
        db.close()


class TestSubmit:
    def test_submit_all_success(self, client, sample_csv_bytes):
        task = upload(client, sample_csv_bytes)
        resp = client.post(f"/api/tasks/{task['id']}/submit")
        assert resp.status_code == 200
        task = resp.json()
        assert task["status"] == TaskStatus.COMPLETED
        assert task["success_count"] == 2
        assert task["failed_count"] == 0
        assert task["timeout_count"] == 0

        batches = client.get(f"/api/tasks/{task['id']}/batches").json()
        assert batches["total"] == 1
        assert batches["items"][0]["status"] == BatchStatus.SUCCESS

    def test_submit_partial_failure(self, client, sample_csv_bytes):
        task = upload(client, sample_csv_bytes)
        fail_ids = get_valid_id_cards(task["id"])[:1]
        app.state.external_client = SimulatedExternalClient(latency=0, fail_id_cards=set(fail_ids))

        task = client.post(f"/api/tasks/{task['id']}/submit").json()
        assert task["success_count"] == 1
        assert task["failed_count"] == 1

        batches = client.get(f"/api/tasks/{task['id']}/batches").json()
        assert batches["items"][0]["status"] == BatchStatus.PARTIAL_FAILED

        failed = client.get(f"/api/tasks/{task['id']}/records",
                            params={"status": RecordStatus.FAILED}).json()
        assert failed["total"] == 1
        assert "外部平台拒绝" in failed["items"][0]["error_msg"]

    def test_batch_timeout_and_retry(self, client, sample_csv_bytes):
        task = upload(client, sample_csv_bytes)
        # 该任务只有2条有效记录 → 1个批次，批次号可预测
        batch_no = f"{task['task_no']}-B001"
        app.state.external_client = SimulatedExternalClient(
            latency=0, timeout_batch_nos={batch_no})

        task = client.post(f"/api/tasks/{task['id']}/submit").json()
        assert task["status"] == TaskStatus.COMPLETED
        assert task["timeout_count"] == 2

        batches = client.get(f"/api/tasks/{task['id']}/batches").json()
        batch = batches["items"][0]
        assert batch["status"] == BatchStatus.TIMEOUT
        assert batch["retryable"] is True

        # 重试：模拟客户端对该批次仅首次超时，重试应成功
        resp = client.post(f"/api/batches/{batch['id']}/retry")
        assert resp.status_code == 200
        assert resp.json()["status"] == BatchStatus.SUCCESS
        assert resp.json()["retry_count"] == 1

        task = client.get(f"/api/tasks/{task['id']}").json()
        assert task["success_count"] == 2
        assert task["timeout_count"] == 0

    def test_retry_non_retryable_batch_rejected(self, client, sample_csv_bytes):
        task = upload(client, sample_csv_bytes)
        client.post(f"/api/tasks/{task['id']}/submit")
        batch = client.get(f"/api/tasks/{task['id']}/batches").json()["items"][0]
        assert batch["status"] == BatchStatus.SUCCESS
        resp = client.post(f"/api/batches/{batch['id']}/retry")
        assert resp.status_code == 409

    def test_submit_invalid_state_rejected(self, client, sample_csv_bytes):
        task = upload(client, sample_csv_bytes)
        client.post(f"/api/tasks/{task['id']}/submit")
        resp = client.post(f"/api/tasks/{task['id']}/submit")  # 已完成，不可重复提交
        assert resp.status_code == 409

    def test_submit_not_found(self, client):
        assert client.post("/api/tasks/99999/submit").status_code == 404

    def test_multiple_batches(self, client):
        # 250 条有效记录 → 3 个批次（100/100/50）
        from conftest import make_id_card
        lines = ["身份证号,姓名,缴费月份,缴费金额,单位编号"]
        for i in range(250):
            idc = make_id_card(f"1101011990{(i % 12) + 1:02d}{(i % 28) + 1:02d}{i % 1000:03d}")
            lines.append(f"{idc},员工{i:03d},2026-08,1000.00,1101010001")
        content = "\n".join(lines).encode()
        task = upload(client, content)
        assert task["valid_count"] == 250

        task = client.post(f"/api/tasks/{task['id']}/submit").json()
        assert task["success_count"] == 250
        batches = client.get(f"/api/tasks/{task['id']}/batches").json()
        assert batches["total"] == 3
        assert [b["record_count"] for b in batches["items"]] == [100, 100, 50]


class TestErrorDownload:
    def test_download_errors_csv(self, client, sample_csv_bytes):
        task = upload(client, sample_csv_bytes)
        fail_ids = get_valid_id_cards(task["id"])[:1]
        app.state.external_client = SimulatedExternalClient(latency=0, fail_id_cards=set(fail_ids))
        client.post(f"/api/tasks/{task['id']}/submit")

        resp = client.get(f"/api/tasks/{task['id']}/errors/download")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert "attachment" in resp.headers["content-disposition"]

        text = resp.content.decode("utf-8-sig")
        lines = [l for l in text.strip().split("\n") if l]
        assert lines[0].startswith("行号,身份证号")
        # 6 条校验错误 + 1 条提交失败
        assert len(lines) == 8
        assert "校验错误" in text
        assert "提交失败" in text

    def test_download_not_found(self, client):
        assert client.get("/api/tasks/99999/errors/download").status_code == 404
