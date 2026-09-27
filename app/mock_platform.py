# -*- coding: utf-8 -*-
"""模拟外部社保缴费上送平台(独立进程)。

行为模拟:
- 正常处理耗时 0.3~1.5s; 约12%请求卡顿3.5s -> 触发客户端超时
- 约5%请求返回HTTP500 -> 批次失败
- 记录级业务拒绝: 金额>50000 -> 超上限; 身份证999开头 -> 人员不存在; 5%随机繁忙
- 幂等: 同一 batch_key 重复提交直接返回首次结果(模拟真实平台防重)
"""
import json
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 9100
_store = {}
_lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, status, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"status": "up"})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/submit":
            return self._send(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "bad json"})
        key = payload.get("batch_key")
        with _lock:
            if key in _store:                      # 幂等: 重试返回原结果
                return self._send(200, _store[key])

        delay = 3.5 if random.random() < 0.12 else random.uniform(0.3, 1.5)
        time.sleep(delay)
        if random.random() < 0.05:
            return self._send(500, {"error": "平台内部错误"})

        results = []
        for rec in payload.get("records", []):
            r = {"row_no": rec.get("row_no"), "success": True, "error": None}
            try:
                amt = float(rec.get("amount") or 0)
            except ValueError:
                amt = 0
            if amt > 50000:
                r.update(success=False, error="超过单笔缴费上限50000")
            elif str(rec.get("id_card") or "").startswith("999"):
                r.update(success=False, error="人员信息不存在")
            elif random.random() < 0.05:
                r.update(success=False, error="平台系统繁忙,请重试")
            results.append(r)

        resp = {"platform_batch_id": "PF%d%03d" % (int(time.time()), random.randint(0, 999)),
                "batch_key": key, "results": results}
        with _lock:
            _store[key] = resp
        self._send(200, resp)


if __name__ == "__main__":
    print("[模拟平台] 外部社保平台已启动: http://127.0.0.1:%d" % PORT)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
