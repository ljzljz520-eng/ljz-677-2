"""预置单位数据"""
from .models import Unit

SEED_UNITS = [
    ("1101010001", "北京示例科技有限公司"),
    ("1101010002", "上海示例制造有限公司"),
    ("3101040003", "广州示例贸易有限公司"),
    ("4403050004", "深圳示例服务有限公司"),
    ("3301060005", "杭州示例网络科技有限公司"),
]


def seed_units(db) -> int:
    """单位表为空时写入预置单位，返回写入数量"""
    if db.query(Unit).count() > 0:
        return 0
    for code, name in SEED_UNITS:
        db.add(Unit(unit_code=code, unit_name=name))
    db.commit()
    return len(SEED_UNITS)
