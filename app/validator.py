# -*- coding: utf-8 -*-
"""缴费记录校验: 身份证号 / 缴费月份 / 金额 / 单位编号"""
import re
from datetime import datetime

import config

# GB11643-1999 校验位权重与对照表
_ID_WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
_ID_CHECK = "10X98765432"


def check_id_card(id_card):
    """返回 None 表示通过, 否则返回错误原因"""
    if id_card is None or str(id_card).strip() == "":
        return "身份证号为空"
    s = str(id_card).strip().upper()
    if len(s) == 15:
        return "15位身份证号, 请升级为18位"
    if len(s) != 18:
        return "身份证号长度须为18位"
    if not re.fullmatch(r"\d{17}[\dX]", s):
        return "身份证号格式非法(前17位为数字, 末位为数字或X)"
    try:
        birth = datetime(int(s[6:10]), int(s[10:12]), int(s[12:14]))
    except ValueError:
        return "出生日期非法"
    if birth.year < 1900 or birth > datetime.now():
        return "出生日期超出合理范围"
    total = sum(int(s[i]) * _ID_WEIGHTS[i] for i in range(17))
    if _ID_CHECK[total % 11] != s[17]:
        return "身份证号校验位错误"
    return None


def check_month(month):
    if month is None or str(month).strip() == "":
        return "缴费月份为空"
    s = str(month).strip()
    if not re.fullmatch(r"\d{6}", s):
        return "月份格式须为YYYYMM"
    y, m = int(s[:4]), int(s[4:6])
    if not 1 <= m <= 12:
        return "月份须在01-12之间"
    n = datetime.now()
    if y * 100 + m > n.year * 100 + n.month:
        return "缴费月份不能晚于当前月份"
    if s < config.MIN_MONTH:
        return "缴费月份不能早于%s" % config.MIN_MONTH
    return None


def check_amount(amount):
    if amount is None or str(amount).strip() == "":
        return "缴费金额为空"
    s = str(amount).strip()
    if not re.fullmatch(r"\d+(\.\d{1,2})?", s):
        return "金额须为数字且最多两位小数"
    v = float(s)
    if v <= 0:
        return "金额必须大于0"
    if v > config.MAX_AMOUNT:
        return "金额超过上限%.2f" % config.MAX_AMOUNT
    return None


def check_unit_code(unit_code, known_units):
    if unit_code is None or str(unit_code).strip() == "":
        return "单位编号为空"
    s = str(unit_code).strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{6,12}", s):
        return "单位编号须为6-12位字母或数字"
    if s not in known_units:
        return "单位编号不存在"
    return None


def validate_record(rec, known_units):
    """对单条记录执行全部校验, 返回错误信息列表"""
    errors = []
    for err in (check_id_card(rec.get("id_card")),
                check_month(rec.get("month")),
                check_amount(rec.get("amount")),
                check_unit_code(rec.get("unit_code"), known_units)):
        if err:
            errors.append(err)
    return errors
