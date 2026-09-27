# -*- coding: utf-8 -*-
"""全局配置"""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
DB_PATH = os.path.join(DATA_DIR, "sibs.db")

MAIN_PORT = 8080                 # 主服务端口
MOCK_PORT = 9100                 # 模拟外部平台端口

BATCH_SIZE = 100                 # 每批上送记录数
PLATFORM_URL = os.environ.get("PLATFORM_URL", "http://127.0.0.1:9100")
PLATFORM_TIMEOUT = 2.0           # 平台响应超时(秒), 超过记为超时批次
MAX_RETRY = 3                    # 批次最大重试次数
SUBMIT_WORKERS = 3               # 并发上送线程数

MIN_MONTH = "202001"             # 允许最早缴费月份
MAX_AMOUNT = 999999.99           # 单笔金额上限
