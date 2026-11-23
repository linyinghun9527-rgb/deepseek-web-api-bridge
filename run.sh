#!/bin/bash
# DeepSeek Web API Bridge - 启动脚本 (macOS / MacBook Air)
# 用法: ./run.sh           前台启动
#       ./run.sh bg        后台启动 (nohup, 日志 logs/bridge.log)
#       ./run.sh stop      停止后台进程
set -euo pipefail
cd "$(dirname "$0")"

PW_CACHE="$HOME/Library/Application Support/cn.org.hermesagent.desktop/runtime/hermes-home/cache/ms-playwright"
if [ -d "$PW_CACHE" ]; then
  export PLAYWRIGHT_BROWSERS_PATH="$PW_CACHE"
fi
export PYTHONUNBUFFERED=1

PY=".venv/bin/python"
[ -x "$PY" ] || { echo "缺少 .venv，请先 uv venv --python 3.12 .venv && uv pip install -r requirements.txt"; exit 1; }

PORT="$(grep -E '^PORT=' .env 2>/dev/null | cut -d= -f2)"
PORT="${PORT:-8000}"

is_up() { curl -s -o /dev/null -m 2 "http://127.0.0.1:${PORT}/api/health"; }

# 主节点守护：如果 .env 里配了 PRIMARY_URL（例如 MacBook 指向 mini），
# 且主节点在线，就拒绝在本机启动——同一 DeepSeek 账号只能有一个桥在跑。
PRIMARY_URL="$(grep -E '^PRIMARY_URL=' .env 2>/dev/null | cut -d= -f2- || true)"
primary_up() {
  [ -n "${PRIMARY_URL}" ] || return 1
  curl -s -o /dev/null -m 3 "${PRIMARY_URL%/}/api/health"
}
guard_primary() {
  [ "${FORCE:-0}" = "1" ] && return 0
  if primary_up; then
    echo "!! 主节点在线（${PRIMARY_URL}），本机不再启动。"
    echo "   同一个 DeepSeek 账号只能有一个桥，两个同跑会把登录态搞掉。"
    echo "   确需在本机临时启动：FORCE=1 ./run.sh $1"
    exit 1
  fi
  return 0
}

case "${1:-fg}" in
  fg)
    guard_primary fg
    if is_up; then echo "端口 ${PORT} 已被占用，已有一个实例在跑（不要开第二个，会抢同一个 DeepSeek 账号）"; exit 1; fi
    exec "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
    ;;
  status)
    if is_up; then echo "运行中: $(curl -s -m 3 http://127.0.0.1:${PORT}/api/health)"; else echo "未运行"; fi
    ;;
  bg)
    guard_primary bg
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
