"""导入与校验流程测试"""
from app.models import RecordStatus, Task, TaskStatus


def upload(client, content: bytes, filename="test.csv"):
    return client.post("/api/tasks/upload", files={"file": (filename, content, "text/csv")})


class TestUpload:
    def test_upload_and_validate(self, client, sample_csv_bytes):
        resp = upload(client, sample_csv_bytes)
        assert resp.status_code == 200
        task = resp.json()
        assert task["status"] == TaskStatus.VALIDATED
        assert task["total_count"] == 8
        # 8行中：2行正常；身份证错/月份错/金额错/单位错/小数错/重复 各1行
        assert task["valid_count"] == 2
        assert task["invalid_count"] == 6

    def test_error_messages_written(self, client, sample_csv_bytes):
        task = upload(client, sample_csv_bytes).json()
        records = client.get(f"/api/tasks/{task['id']}/records",
                             params={"status": RecordStatus.INVALID, "size": 100}).json()
        assert records["total"] == 6
        msgs = {r["row_no"]: r["error_msg"] for r in records["items"]}
        assert "校验位" in msgs[4] or "长度" in msgs[4]
        assert "YYYY-MM" in msgs[5]
        assert "有效数字" in msgs[6]
        assert "未登记" in msgs[7]
        assert "两位小数" in msgs[8]
        assert "重复" in msgs[9]

    def test_empty_file_rejected(self, client):
        resp = upload(client, b"")
        assert resp.status_code == 400

    def test_bad_header_rejected(self, client):
        resp = upload(client, "a,b,c\n1,2,3\n".encode())
        assert resp.status_code == 400
        assert "缺少必需列" in resp.json()["detail"]

    def test_english_header_supported(self, client, sample_csv_bytes):
        text = sample_csv_bytes.decode("utf-8-sig")
        text = text.replace("身份证号,姓名,缴费月份,缴费金额,单位编号",
                            "id_card,name,month,amount,unit_code")
        resp = upload(client, text.encode())
        assert resp.status_code == 200
        assert resp.json()["total_count"] == 8

    def test_gbk_encoding_supported(self, client, sample_csv_bytes):
        text = sample_csv_bytes.decode("utf-8-sig")
        resp = upload(client, text.encode("gbk"))
        assert resp.status_code == 200
        assert resp.json()["valid_count"] == 2

    def test_blank_lines_ignored(self, client, sample_csv_bytes):
        text = sample_csv_bytes.decode("utf-8-sig") + "\n\n,,,\n"
        resp = upload(client, text.encode())
        assert resp.status_code == 200
        assert resp.json()["total_count"] == 8

    def test_task_persisted(self, client, db_session, sample_csv_bytes):
        task = upload(client, sample_csv_bytes).json()
        t = db_session.get(Task, task["id"])
        assert t is not None and t.total_count == 8
