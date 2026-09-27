import os
import tempfile

# 必须在导入 app 之前设置：独立测试数据库 + 后台任务同步执行
_tmpdir = tempfile.mkdtemp(prefix="sip_test_")
os.environ["SIP_DB_PATH"] = os.path.join(_tmpdir, "test.db")
os.environ["SIP_SYNC"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed_units  # noqa: E402
from app.services.external_client import SimulatedExternalClient  # noqa: E402
from app.validators import compute_id_card_check_code  # noqa: E402


def make_id_card(base17: str) -> str:
    """根据17位基数生成带正确校验位的身份证号"""
    return base17 + compute_id_card_check_code(base17)


@pytest.fixture()
def db_session():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    seed_units(db)
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client(db_session):
    # 默认确定性外部平台：全部成功
    app.state.external_client = SimulatedExternalClient(latency=0)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def sample_csv_bytes():
    """构造一份包含各类异常的 CSV"""
    id1 = make_id_card("11010119900307001")
    id2 = make_id_card("31010419850512002")
    id3 = make_id_card("44030519771123003")
    id4 = make_id_card("33010619920214004")
    id5 = make_id_card("11010119881230005")
    id6 = make_id_card("31010419990101006")
    id7 = make_id_card("44030519840717007")
    lines = [
        "身份证号,姓名,缴费月份,缴费金额,单位编号",
        f"{id1},张三,2026-08,1500.00,1101010001",          # 正常
        f"{id2},李四,2026-08,2360.50,3101040003",          # 正常
        f"{id3}X,王五,2026-08,800.00,4403050004",          # 身份证校验位错误（19位）
        f"{id4},赵六,2026-13,900.00,3301060005",           # 非法月份
        f"{id5},钱七,2026-08,abc,1101010001",              # 金额非数字
        f"{id6},孙八,2026-08,1200.00,9999999999",          # 单位未登记
        f"{id7},周九,2026-08,100.999,1101010002",          # 金额三位小数
        f"{id1},张三,2026-08,1500.00,1101010001",          # 与第1行同人同月重复
    ]
    return "\n".join(lines).encode("utf-8-sig")
