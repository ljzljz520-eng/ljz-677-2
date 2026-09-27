# -*- coding: utf-8 -*-
"""外部社保平台上送客户端(HTTP, 带超时控制)"""
import json
import socket
import urllib.error
import urllib.request

import config


class PlatformTimeout(Exception):
    """平台响应超时"""


class PlatformError(Exception):
    """平台返回错误或连接失败"""


def submit_batch(batch_key, records):
    """提交一个批次, 返回平台响应 dict。

    batch_key: 幂等键(数据库批次ID), 重试时平台据此返回原结果, 避免重复入账。
    records: [{"row_no","person_name","id_card","month","amount","unit_code"}, ...]
    超时抛 PlatformTimeout, 其余异常抛 PlatformError。
    """
    payload = json.dumps({"batch_key": batch_key, "records": records}).encode("utf-8")
    req = urllib.request.Request(
        config.PLATFORM_URL.rstrip("/") + "/submit",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=config.PLATFORM_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise PlatformError("平台HTTP错误: %s" % e.code)
    except urllib.error.URLError as e:
        if isinstance(e.reason, (socket.timeout, TimeoutError)):
            raise PlatformTimeout("平台响应超时(>%ss)" % config.PLATFORM_TIMEOUT)
        raise PlatformError("平台连接失败: %s" % e.reason)
    except (socket.timeout, TimeoutError):
        raise PlatformTimeout("平台响应超时(>%ss)" % config.PLATFORM_TIMEOUT)
