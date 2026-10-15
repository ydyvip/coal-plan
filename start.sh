#!/usr/bin/env bash
# 一键启动（生产模式：后端同时托管已构建的前端）。开发模式见 README §4。
set -e
cd "$(dirname "$0")/backend"
pip install -r requirements.txt --break-system-packages -q 2>/dev/null || pip install -r requirements.txt -q
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
