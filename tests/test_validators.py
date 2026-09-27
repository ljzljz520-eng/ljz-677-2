"""字段校验规则单元测试"""
from datetime import date
from decimal import Decimal

from app.validators import (
    compute_id_card_check_code,
    validate_amount,
    validate_id_card,
    validate_month,
    validate_name,
    validate_unit_code,
)


def make_id(base17: str) -> str:
    return base17 + compute_id_card_check_code(base17)


class TestIdCard:
    def test_valid(self):
        ok, _ = validate_id_card(make_id("11010119900307001"))
        assert ok

    def test_valid_with_x(self):
        # 构造校验位为 X 的号码
        for i in range(1000):
            base = f"11010119900307{i:03d}"
            if compute_id_card_check_code(base) == "X":
                ok, _ = validate_id_card(base + "X")
                assert ok
                return
        raise AssertionError("未找到校验位为X的样本")

    def test_lowercase_x_accepted(self):
        for i in range(1000):
            base = f"11010119900307{i:03d}"
            if compute_id_card_check_code(base) == "X":
                ok, _ = validate_id_card(base + "x")
                assert ok
                return

    def test_wrong_check_code(self):
        ok, msg = validate_id_card(make_id("11010119900307001")[:-1] + "9")
        assert not ok and "校验位" in msg

    def test_wrong_length(self):
        ok, msg = validate_id_card("110101199003070")
        assert not ok and "18位" in msg

    def test_invalid_birth_date(self):
        ok, msg = validate_id_card(make_id("11010119901330001"))  # 13月30日
        assert not ok and "出生日期" in msg

    def test_non_digit(self):
        ok, msg = validate_id_card("1101011990030700AB")
        assert not ok

    def test_empty(self):
        ok, msg = validate_id_card("")
        assert not ok and "为空" in msg


class TestMonth:
    TODAY = date(2026, 9, 27)

    def test_valid(self):
        ok, _ = validate_month("2026-09", self.TODAY)
        assert ok

    def test_boundary_min(self):
        ok, _ = validate_month("2000-01", self.TODAY)
        assert ok

    def test_future_month(self):
        ok, msg = validate_month("2026-10", self.TODAY)
        assert not ok and "晚于当前月" in msg

    def test_too_early(self):
        ok, msg = validate_month("1999-12", self.TODAY)
        assert not ok and "过早" in msg

    def test_bad_format(self):
        for bad in ["2026/09", "2026-9", "2026-13", "202609", "abc"]:
            ok, msg = validate_month(bad, self.TODAY)
            assert not ok, bad

    def test_empty(self):
        ok, _ = validate_month("", self.TODAY)
        assert not ok


class TestAmount:
    def test_valid(self):
        ok, _, amt = validate_amount("1500.00")
        assert ok and amt == Decimal("1500.00")

    def test_integer_amount(self):
        ok, _, amt = validate_amount("800")
        assert ok and amt == Decimal("800.00")

    def test_min_boundary(self):
        ok, _, _ = validate_amount("0.01")
        assert ok

    def test_max_boundary(self):
        ok, _, _ = validate_amount("999999.99")
        assert ok

    def test_zero_and_negative(self):
        assert not validate_amount("0")[0]
        assert not validate_amount("-5.00")[0]

    def test_too_large(self):
        ok, msg, _ = validate_amount("1000000.00")
        assert not ok and "上限" in msg

    def test_too_many_decimals(self):
        ok, msg, _ = validate_amount("100.999")
        assert not ok and "两位小数" in msg

    def test_not_a_number(self):
        ok, msg, _ = validate_amount("abc")
        assert not ok and "有效数字" in msg

    def test_empty(self):
        ok, _, _ = validate_amount("  ")
        assert not ok


class TestOthers:
    def test_name(self):
        assert validate_name("张三")[0]
        assert not validate_name("")[0]
        assert not validate_name("x" * 65)[0]

    def test_unit_code(self):
        codes = {"1101010001"}
        assert validate_unit_code("1101010001", codes)[0]
        ok, msg = validate_unit_code("9999999999", codes)
        assert not ok and "未登记" in msg
        assert not validate_unit_code("", codes)[0]
