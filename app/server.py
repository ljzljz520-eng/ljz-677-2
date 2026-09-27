# -*- coding: utf-8 -*-
"""社保缴费清单上送台 - 主服务(仅标准库)"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import config
import db
import service

STATIC_DIR = os.path.join(config.BASE_DIR, "static")
ROUTES = []


def route(method, pattern):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn))
        return fn
    return deco


def ok(data=None, **kw):
    body = {"code": 0, "msg": "ok"}
    if data is not None:
        body["data"] = data
    body.update(kw)
    return 200, body


# ---------------- 路由 ----------------

@route("GET", r"/api/tasks")
def list_tasks(h, m, q):
    rows = db.query_all("SELECT * FROM tasks ORDER BY id DESC LIMIT 200")
    return ok(rows)


@route("POST", r"/api/tasks")
def create_task(h, m, q):
    fields, files = h.multipart()
    if "file" not in files:
        return 400, {"code": 1, "msg": "缺少上传文件(file)"}
    filename, content = files["file"]
    if not filename.lower().endswith(".csv"):
        return 400, {"code": 1, "msg": "仅支持CSV文件"}
    task_id = service.import_task(fields.get("name", ""), filename, content)
    return ok({"task_id": task_id})


@route("GET", r"/api/tasks/(\d+)")
def task_detail(h, m, q):
    task = db.query_one("SELECT * FROM tasks WHERE id=?", (m.group(1),))
    if not task:
        return 404, {"code": 1, "msg": "任务不存在"}
    return ok(task)


@route("POST", r"/api/tasks/(\d+)/validate")
def validate(h, m, q):
    return ok(service.validate_task(int(m.group(1))))


@route("POST", r"/api/tasks/(\d+)/submit")
def submit(h, m, q):
    return ok(service.submit_task(int(m.group(1))))


@route("GET", r"/api/tasks/(\d+)/records")
def records(h, m, q):
    task_id = m.group(1)
    page, size = int(q.get("page", [1])[0]), min(int(q.get("size", [50])[0]), 200)
    where, args = "task_id=?", [task_id]
    status = q.get("status", [""])[0]
    if status == "invalid":
        where += " AND validate_status='INVALID'"
    elif status == "failed":
        where += " AND submit_status='FAILED'"
    elif status == "success":
        where += " AND submit_status='SUCCESS'"
    elif status == "valid":
        where += " AND validate_status='VALID'"
    total = db.query_one("SELECT COUNT(*) c FROM records WHERE " + where, args)["c"]
    rows = db.query_all(
        "SELECT * FROM records WHERE " + where + " ORDER BY row_no LIMIT ? OFFSET ?",
        args + [size, (page - 1) * size])
    return ok({"total": total, "page": page, "size": size, "rows": rows})


@route("GET", r"/api/tasks/(\d+)/batches")
def batches(h, m, q):
    rows = db.query_all("SELECT * FROM batches WHERE task_id=? ORDER BY batch_no", (m.group(1),))
    return ok(rows)


@route("POST", r"/api/batches/(\d+)/retry")
def retry(h, m, q):
    return ok(service.retry_batch(int(m.group(1))))


@route("GET", r"/api/tasks/(\d+)/errors\.csv")
def errors_csv(h, m, q):
    content = service.error_csv(int(m.group(1)))
    return 200, ("__file__", content.encode("utf-8"),
                 "text/csv; charset=utf-8",
                 "attachment; filename=task_%s_errors.csv" % m.group(1))


@route("GET", r"/api/units")
def units(h, m, q):
    return ok(db.query_all("SELECT * FROM units ORDER BY unit_code"))


# ---------------- HTTP 处理 ----------------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def multipart(self):
        ctype = self.headers.get("Content-Type", "")
        boundary = re.search(r"boundary=([^;]+)", ctype)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        if not boundary:
            return {}, {}
        token = b"--" + boundary.group(1).strip().strip('"').encode()
        fields, files = {}, {}
        for part in body.split(token):
            part = part.strip(b"\r\n")
            if not part or part == b"--":
                continue
            if part.endswith(b"--"):
                part = part[:-2].rstrip(b"\r\n")
            head, sep, content = part.partition(b"\r\n\r\n")
            if not sep:
                continue
            head = head.decode("utf-8", "replace")
            name_m = re.search(r'name="([^"]+)"', head)
            if not name_m:
                continue
            file_m = re.search(r'filename="([^"]*)"', head)
            if file_m:
                files[name_m.group(1)] = (file_m.group(1), content)
            else:
                fields[name_m.group(1)] = content.decode("utf-8", "replace")
        return fields, files

    def _send(self, status, payload):
        if isinstance(payload, tuple) and payload and payload[0] == "__file__":
            _, data, ctype, disp = payload
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Disposition", disp)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self, method):
        parsed = urlparse(self.path)
        path, q = parsed.path, parse_qs(parsed.query)
        if method == "GET" and (path == "/" or path == "/index.html"):
            return self._serve_static("index.html")
        for mth, pattern, fn in ROUTES:
            if mth != method:
                continue
            m = pattern.match(path)
            if m:
                try:
                    status, payload = fn(self, m, q)
                except ValueError as e:
                    status, payload = 400, {"code": 1, "msg": str(e)}
                except Exception as e:
                    status, payload = 500, {"code": 1, "msg": "服务器内部错误: %s" % e}
                return self._send(status, payload)
        self._send(404, {"code": 1, "msg": "接口不存在: %s %s" % (method, path)})

    def _serve_static(self, name):
        fp = os.path.join(STATIC_DIR, name)
        if not os.path.isfile(fp):
            return self._send(404, {"code": 1, "msg": "页面不存在"})
        with open(fp, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")


def main():
    db.init_db()
    server = ThreadingHTTPServer(("0.0.0.0", config.MAIN_PORT), Handler)
    print("[主服务] 社保缴费清单上送台已启动: http://127.0.0.1:%d" % config.MAIN_PORT)
    print("[主服务] 外部平台地址: %s (超时%ss, 每批%d条)" %
          (config.PLATFORM_URL, config.PLATFORM_TIMEOUT, config.BATCH_SIZE))
    server.serve_forever()


if __name__ == "__main__":
    main()
