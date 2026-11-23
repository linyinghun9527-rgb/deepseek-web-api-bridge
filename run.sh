#!/bin/bash
# DeepSeek Web API Bridge - 启动脚本 (macOS / MacBook Air)
# 用法: ./run.sh           前台启动
#       ./run.sh bg        后台启动 (nohup, 日志 logs/bridge.log)
#       ./run.sh stop      停止后台进程
set -euo pipefail
cd "$(dirname "$0")"

export PLAYWRIGHT_BROWSERS_PATH="$HOME/Library/Application Support/cn.org.hermesagent.desktop/runtime/hermes-home/cache/ms-playwright"
export PYTHONUNBUFFERED=1

PY=".venv/bin/python"
[ -x "$PY" ] || { echo "缺少 .venv，请先 uv venv --python 3.12 .venv && uv pip install -r requirements.txt"; exit 1; }

PORT="$(grep -E '^PORT=' .env 2>/dev/null | cut -d= -f2)"
PORT="${PORT:-8000}"

is_up() { curl -s -o /dev/null -m 2 "http://127.0.0.1:${PORT}/api/health"; }

case "${1:-fg}" in
  fg)
    if is_up; then echo "端口 ${PORT} 已被占用，已有一个实例在跑（不要开第二个，会抢同一个 DeepSeek 账号）"; exit 1; fi
    exec "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
    ;;
  status)
    if is_up; then echo "运行中: $(curl -s -m 3 http://127.0.0.1:${PORT}/api/health)"; else echo "未运行"; fi
    ;;
  bg)
    if is_up; then
      echo "已在运行（端口 ${PORT} 有响应），不重复启动。要重启请先 ./run.sh stop"
      exit 1
    fi
    mkdir -p logs
    nohup "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" >> logs/bridge.log 2>&1 &
    echo $! > logs/bridge.pid
    echo "started pid=$(cat logs/bridge.pid) port=$PORT log=logs/bridge.log"
    ;;
  stop)
    if [ -f logs/bridge.pid ]; then
      kill "$(cat logs/bridge.pid)" 2>/dev/null && echo "stopped" || echo "not running"
      rm -f logs/bridge.pid
    else
      pkill -f "uvicorn app.main:app" && echo "stopped by pkill" || echo "not running"
    fi
    ;;
  *)
    echo "usage: $0 [fg|bg|stop]"; exit 2;;
esac
