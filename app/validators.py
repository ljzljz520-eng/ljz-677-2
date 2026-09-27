"""缴费记录字段校验规则"""
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional, Tuple

# GB 11643-1999 身份证校验位权重与校验码
ID_CARD_WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
ID_CARD_CHECK_CODES = ["1", "0", "X", "9", "8", "7", "6", "5", "4", "3", "2"]

MIN_AMOUNT = Decimal("0.01")
MAX_AMOUNT = Decimal("999999.99")
MIN_MONTH_YEAR = 2000

MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
ID_CARD_RE = re.compile(r"^\d{17}[\dX]$")


def compute_id_card_check_code(base17: str) -> str:
    """根据前17位计算身份证校验码"""
    total = sum(int(base17[i]) * ID_CARD_WEIGHTS[i] for i in range(17))
    return ID_CARD_CHECK_CODES[total % 11]


def validate_id_card(id_card: Optional[str]) -> Tuple[bool, str]:
    """校验18位身份证号：格式、出生日期、校验位"""
    if not id_card or not id_card.strip():
        return False, "身份证号为空"
    code = id_card.strip().upper()
    if len(code) != 18:
        return False, f"身份证号长度应为18位，实际{len(code)}位"
    if not ID_CARD_RE.match(code):
        return False, "身份证号格式错误（前17位须为数字，末位为数字或X）"
    try:
        birth = date(int(code[6:10]), int(code[10:12]), int(code[12:14]))
    except ValueError:
        return False, "身份证号中的出生日期无效"
    if birth > date.today():
        return False, "身份证号中的出生日期晚于当前日期"
    if compute_id_card_check_code(code) != code[17]:
        return False, "身份证号校验位错误"
    return True, ""


def validate_month(month: Optional[str], today: Optional[date] = None) -> Tuple[bool, str]:
    """校验缴费月份：YYYY-MM，范围 2000-01 至当前月"""
    if not month or not month.strip():
        return False, "缴费月份为空"
    m = month.strip()
    match = MONTH_RE.match(m)
    if not match:
        return False, f"缴费月份格式错误（应为YYYY-MM）：{m}"
    year, mon = int(match.group(1)), int(match.group(2))
    if year < MIN_MONTH_YEAR:
        return False, f"缴费月份过早（不得早于{MIN_MONTH_YEAR}-01）：{m}"
    today = today or date.today()
    if (year, mon) > (today.year, today.month):
        return False, f"缴费月份不能晚于当前月：{m}"
    return True, ""


def validate_amount(raw: Optional[str]) -> Tuple[bool, str, Optional[Decimal]]:
    """校验缴费金额：0.01 ~ 999999.99，最多两位小数"""
    if raw is None or not str(raw).strip():
        return False, "缴费金额为空", None
    s = str(raw).strip()
    try:
        amount = Decimal(s)
    except InvalidOperation:
        return False, f"缴费金额不是有效数字：{s}", None
    if amount.is_nan() or amount.is_infinite():
        return False, f"缴费金额不是有效数字：{s}", None
    if amount < MIN_AMOUNT:
        return False, f"缴费金额必须不小于{MIN_AMOUNT}：{s}", None
    if amount > MAX_AMOUNT:
        return False, f"缴费金额超过上限{MAX_AMOUNT}：{s}", None
    if amount != amount.quantize(Decimal("0.01")):
        return False, f"缴费金额最多支持两位小数：{s}", None
    return True, "", amount.quantize(Decimal("0.01"))


def validate_name(name: Optional[str]) -> Tuple[bool, str]:
    if not name or not name.strip():
        return False, "姓名为空"
    if len(name.strip()) > 64:
        return False, "姓名长度超过64字符"
    return True, ""


def validate_unit_code(unit_code: Optional[str], valid_codes: set) -> Tuple[bool, str]:
    """校验单位编号：非空且已登记"""
    if not unit_code or not unit_code.strip():
        return False, "单位编号为空"
    code = unit_code.strip()
    if code not in valid_codes:
        return False, f"单位编号未登记：{code}"
    return True, ""
