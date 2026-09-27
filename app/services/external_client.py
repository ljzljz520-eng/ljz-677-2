"""外部社保平台客户端（模拟实现）。

真实环境中替换为 HTTP 客户端即可，接口契约：
  submit_batch(batch_no, records) -> list[ {row_ref, success, error} ]
  - records 中每条带 idempotency_key，外部平台据此幂等去重，重试不产生重复入账
  - 整批不可达/超时抛出 BatchTimeoutError
"""
import asyncio
import random
from typing import Optional


class BatchTimeoutError(Exception):
    """批次提交超时"""


class SimulatedExternalClient:
    """模拟外部平台：支持确定性行为（测试）与随机行为（演示）。

    - fail_id_cards: 这些身份证号的记录一律被外部平台拒绝
    - timeout_batch_nos: 这些批次首次提交超时（重试成功），用于演示超时重试
    - fail_rate / timeout_rate: 随机失败/超时比例（演示模式）
    """

    def __init__(
        self,
        latency: float = 0.05,
        fail_id_cards: Optional[set] = None,
        timeout_batch_nos: Optional[set] = None,
        fail_rate: float = 0.0,
        timeout_rate: float = 0.0,
        seed: Optional[int] = None,
    ):
        self.latency = latency
        self.fail_id_cards = set(fail_id_cards or [])
        self.timeout_batch_nos = set(timeout_batch_nos or [])
        self.fail_rate = fail_rate
        self.timeout_rate = timeout_rate
        self._rng = random.Random(seed)
        self._attempts: dict[str, int] = {}
        self._accepted_keys: set[str] = set()  # 模拟幂等去重

    async def submit_batch(self, batch_no: str, records: list[dict]) -> list[dict]:
        await asyncio.sleep(self.latency)
        attempt = self._attempts.get(batch_no, 0) + 1
        self._attempts[batch_no] = attempt

        # 首次提交超时（模拟网络抖动），重试放行
        if attempt == 1 and batch_no in self.timeout_batch_nos:
            raise BatchTimeoutError(f"批次 {batch_no} 提交超时")
        if self.timeout_rate and self._rng.random() < self.timeout_rate:
            raise BatchTimeoutError(f"批次 {batch_no} 提交超时")

        results = []
        for rec in records:
            key = rec["idempotency_key"]
            if key in self._accepted_keys:
                # 幂等命中：与首次提交结果一致（此处简化为成功）
                results.append({"row_ref": rec["row_ref"], "success": True, "error": ""})
                continue
            if rec["id_card"] in self.fail_id_cards:
                results.append({
                    "row_ref": rec["row_ref"],
                    "success": False,
                    "error": "外部平台拒绝：该人员该月已存在缴费记录",
                })
            elif self.fail_rate and self._rng.random() < self.fail_rate:
                results.append({
                    "row_ref": rec["row_ref"],
                    "success": False,
                    "error": "外部平台业务校验失败：缴费基数与单位核定基数不符",
                })
            else:
                self._accepted_keys.add(key)
                results.append({"row_ref": rec["row_ref"], "success": True, "error": ""})
        return results
