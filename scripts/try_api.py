#!/usr/bin/env python3
"""端到端打一次 OpenAI 兼容接口，打印真实回复。"""
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 从 .env 读 API key（不打印）
env = {}
for line in (ROOT / ".env").read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    env[k.strip()] = v.strip().strip('"').strip("'")

key = env.get("BRIDGE_API_KEYS", "").split(",")[0].strip()
base = f"http://127.0.0.1:{env.get('PORT', '8000')}"

prompt = sys.argv[1] if len(sys.argv) > 1 else "只回答两个字：收到"


def post(path, payload, timeout=180):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    import urllib.error
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode(), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), time.time() - t0


print(f"key={'set' if key else 'MISSING'} base={base}")
st, body, el = post("/v1/chat/completions", {
    "model": "deepseek-web",
    "messages": [{"role": "user", "content": prompt}],
    "stream": False,
})
print(f"HTTP {st}  {el:.1f}s")
try:
    data = json.loads(body)
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    print("answer:", repr(msg.get("content")))
    print("usage:", data.get("usage"))
    if not msg.get("content"):
        print("raw:", body[:800])
except Exception:
    print("body:", body[:800])
