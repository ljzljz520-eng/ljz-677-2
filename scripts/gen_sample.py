# -*- coding: utf-8 -*-
"""生成测试用缴费清单CSV: 1000条, 含各类校验错误与平台拒绝场景"""
import csv
import random
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from validator import _ID_WEIGHTS, _ID_CHECK  # noqa

random.seed(20260926)
UNITS = [f"SH1000{i:02d}" for i in range(1, 11)]
SURNAMES = "张王李赵刘陈杨黄周吴徐孙马朱胡郭何高林罗"
GIVEN = ["伟", "芳", "娜", "敏", "静", "磊", "军", "洋", "勇", "艳", "杰", "涛", "明", "超", "雪"]


def make_id(prefix="310104"):
    area = prefix
    birth = "%04d%02d%02d" % (random.randint(1960, 2000), random.randint(1, 12), random.randint(1, 28))
    seq = "%03d" % random.randint(1, 999)
    body = area + birth + seq
    check = _ID_CHECK[sum(int(body[i]) * _ID_WEIGHTS[i] for i in range(17)) % 11]
    return body + check


def main(path, n=1000):
    rows = []
    for i in range(n):
        name = random.choice(SURNAMES) + random.choice(GIVEN) + (random.choice(GIVEN) if random.random() < .5 else "")
        id_card = make_id("310104" if random.random() < .9 else "999999")  # 999开头->平台拒绝
        month = "%04d%02d" % (random.randint(2024, 2026), random.randint(1, 12))
        if month > "202609":
            month = "202608"
        amount = "%.2f" % random.uniform(500, 9000)
        unit = random.choice(UNITS)
        rows.append([name, id_card, month, amount, unit])

    bad = random.sample(range(n), 150)
    for k, idx in enumerate(bad):
        kind = k % 10
        if kind == 0:   # 校验位错误
            r = list(rows[idx]); rows[idx][1] = r[1][:-1] + ("0" if r[1][-1] != "0" else "1")
        elif kind == 1:  # 15位身份证
            rows[idx][1] = rows[idx][1][:6] + rows[idx][1][8:17]
        elif kind == 2:  # 未来月份
            rows[idx][2] = "202712"
        elif kind == 3:  # 月份格式错
            rows[idx][2] = "2026-08"
        elif kind == 4:  # 金额非法
            rows[idx][3] = "-100"
        elif kind == 5:  # 金额三位小数
            rows[idx][3] = "1234.567"
        elif kind == 6:  # 单位编号不存在
            rows[idx][4] = "XX999999"
        elif kind == 7:  # 单位编号过短
            rows[idx][4] = "SH1"
        elif kind == 8:  # 金额超平台上限(本地校验通过, 平台拒绝)
            rows[idx][3] = "60000.00"
        else:            # 身份证为空
            rows[idx][1] = ""

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["姓名", "身份证号", "缴费月份", "缴费金额", "单位编号"])
        w.writerows(rows)
    print("已生成 %s (%d条, 含约150条各类异常)" % (path, n))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/workspace/data/sample.csv",
         int(sys.argv[2]) if len(sys.argv) > 2 else 1000)
