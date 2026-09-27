#!/bin/bash
# 启动社保缴费清单上送台(主服务 + 模拟外部平台)
cd "$(dirname "$0")"
mkdir -p data
python3 app/mock_platform.py & echo $! > data/mock.pid
sleep 0.5
python3 app/server.py & echo $! > data/server.pid
echo "主服务: http://127.0.0.1:8080   模拟平台: http://127.0.0.1:9100"
echo "停止: kill \$(cat data/server.pid data/mock.pid)"
