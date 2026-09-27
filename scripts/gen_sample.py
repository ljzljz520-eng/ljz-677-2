#!/usr/bin/env python3
"""生成示例缴费清单 CSV（含一定比例的异常数据，用于演示校验与错误明细）"""
import argparse
import csv
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.validators import compute_id_card_check_code  # noqa: E402

REGIONS = ["110101", "310104", "440305", "330106", "320508"]
UNIT_CODES = ["1101010001", "1101010002", "3101040003", "4403050004", "3301060005"]
SURNAMES = "王李张刘陈杨赵黄周吴徐孙马朱胡郭何林罗郑"
GIVEN = "伟芳娜敏静丽强磊军洋勇艳杰娟涛明超秀兰霞平刚桂英华玉萍红"


def make_id_card(rng: random.Random) -> str:
    region = rng.choice(REGIONS)
    year = rng.randint(1960, 2002)
    month = rng.randint(1, 12)
    day = rng.randint(1, 28)
    seq = rng.randint(0, 999)
    base = f"{region}{year:04d}{month:02d}{day:02d}{seq:03d}"
    return base + compute_id_card_check_code(base)


def make_name(rng: random.Random) -> str:
    return rng.choice(SURNAMES) + "".join(rng.choices(GIVEN, k=rng.randint(1, 2)))


def main():
    parser = argparse.ArgumentParser(description="生成示例缴费清单 CSV")
    parser.add_argument("--rows", type=int, default=1000, help="数据行数（默认1000）")
    parser.add_argument("--out", default="sample_data.csv", help="输出文件")
    parser.add_argument("--error-rate", type=float, default=0.1, help="异常数据比例（默认0.1）")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    rows = []
    for _ in range(args.rows):
        rows.append({
            "id_card": make_id_card(rng),
            "name": make_name(rng),
            "month": f"2026-{rng.randint(1, 9):02d}",
            "amount": f"{rng.uniform(500, 9000):.2f}",
            "unit_code": rng.choice(UNIT_CODES),
        })

    # 注入异常数据
    n_err = int(args.rows * args.error_rate)
    defect_fns = [
        lambda r: r.update(id_card=r["id_card"][:-1] + ("0" if r["id_card"][-1] != "0" else "1")),  # 校验位错
        lambda r: r.update(id_card=r["id_card"][:17]),                       # 长度不足
        lambda r: r.update(month="2026-13"),                                 # 非法月份
        lambda r: r.update(month="2027-06"),                                 # 未来月份
        lambda r: r.update(month="2026/08"),                                 # 月份格式错
        lambda r: r.update(amount="abc"),                                    # 金额非数字
        lambda r: r.update(amount="-100.00"),                                # 金额为负
        lambda r: r.update(amount="100.999"),                                # 小数位过多
        lambda r: r.update(amount="0"),                                      # 金额为0
        lambda r: r.update(unit_code="9999999999"),                          # 单位未登记
        lambda r: r.update(name=""),                                         # 姓名为空
    ]
    for i in rng.sample(range(len(rows)), min(n_err, len(rows))):
        rng.choice(defect_fns)(rows[i])

    # 注入一对任务内重复（同人同月）
    if len(rows) >= 2:
        rows[1] = dict(rows[0])

    with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["身份证号", "姓名", "缴费月份", "缴费金额", "单位编号"])
        for r in rows:
            writer.writerow([r["id_card"], r["name"], r["month"], r["amount"], r["unit_code"]])
    print(f"已生成 {args.out}：{len(rows)} 行（含约 {n_err} 行异常 + 1 对重复）")


if __name__ == "__main__":
    main()
