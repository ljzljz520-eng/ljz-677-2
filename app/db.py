# -*- coding: utf-8 -*-
"""SQLite 数据访问层(每次调用独立连接, WAL 模式支持并发读写)"""
import os
import sqlite3
from datetime import datetime

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    filename TEXT,
    status TEXT NOT NULL DEFAULT 'IMPORTED',   -- IMPORTED/VALIDATED/SUBMITTING/DONE
    total_count INTEGER DEFAULT 0,
    valid_count INTEGER DEFAULT 0,
    invalid_count INTEGER DEFAULT 0,
    batch_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    timeout_batches INTEGER DEFAULT 0,
    created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    row_no INTEGER NOT NULL,                    -- 原始文件行号(表头为第1行)
    person_name TEXT, id_card TEXT, month TEXT, amount TEXT, unit_code TEXT,
    validate_status TEXT DEFAULT 'PENDING',     -- PENDING/VALID/INVALID
    validate_error TEXT,
    submit_status TEXT DEFAULT 'NONE',          -- NONE/PENDING/SUCCESS/FAILED
    submit_error TEXT,
    batch_id INTEGER,
    created_at TEXT, updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_records_task ON records(task_id, validate_status, submit_status);
CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    batch_no INTEGER NOT NULL,
    record_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'PENDING',              -- PENDING/SUBMITTING/SUCCESS/PARTIAL/FAILED/TIMEOUT
    platform_batch_id TEXT,
    retry_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    error_message TEXT,
    submitted_at TEXT, finished_at TEXT,
    created_at TEXT, updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_batches_task ON batches(task_id, status);
CREATE TABLE IF NOT EXISTS units (
    unit_code TEXT PRIMARY KEY,
    unit_name TEXT NOT NULL
);
"""

SEED_UNITS = [
    ("SH100001", "上海云图科技有限公司"),
    ("SH100002", "上海长风机械制造厂"),
    ("SH100003", "沪上联合物流有限公司"),
    ("SH100004", "东方明州餐饮集团"),
    ("SH100005", "浦江建筑设计研究院"),
    ("SH100006", "申城康泰医药有限公司"),
    ("SH100007", "华东星辉电子科技"),
    ("SH100008", "静安悦读文化传播"),
    ("SH100009", "虹桥迅达汽车服务"),
    ("SH100010", "杨浦绿茵园林绿化"),
]


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_conn():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db():
    conn = get_conn()
    with conn:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) c FROM units").fetchone()["c"] == 0:
            conn.executemany("INSERT INTO units(unit_code, unit_name) VALUES(?,?)", SEED_UNITS)
    conn.close()


def query_all(sql, args=()):
    conn = get_conn()
    rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
    conn.close()
    return rows


def query_one(sql, args=()):
    conn = get_conn()
    row = conn.execute(sql, args).fetchone()
    conn.close()
    return dict(row) if row else None


def execute(sql, args=()):
    conn = get_conn()
    with conn:
        cur = conn.execute(sql, args)
        last_id = cur.lastrowid
    conn.close()
    return last_id


def execute_many(sql, seq):
    conn = get_conn()
    with conn:
        conn.executemany(sql, seq)
    conn.close()
