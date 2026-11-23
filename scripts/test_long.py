#!/usr/bin/env python3
"""长 prompt 测试：模拟 Agent 带大段上下文。"""
import json
import pathlib
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
env = {}
for line in (ROOT / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
key = env["BRIDGE_API_KEYS"].split(",")[0].strip()
base = f"http://127.0.0.1:{env.get('PORT', '8000')}"

filler = "这是一段用于测试长上下文传输的填充文本，内容没有实际意义。" * 80
prompt = (f"{filler}\n\n以上是背景材料。请只回答三个字：已收到")

print(f"prompt 长度: {len(prompt)} 字符")
payload = {"model": "deepseek-web", "stream": False,
           "messages": [{"role": "user", "content": prompt}]}
req = urllib.request.Request(base + "/v1/chat/completions",
                            data=json.dumps(payload).encode(),
                            headers={"Content-Type": "application/json",
                                     "Authorization": f"Bearer {key}"},
                            method="POST")
t0 = time.time()
try:
    with urllib.request.urlopen(req, timeout=240) as r:
        body = r.read().decode()
    d = json.loads(body)
    ans = (d.get("choices") or [{}])[0].get("message", {}).get("content")
    print(f"[{'OK' if ans else 'EMPTY'}] {time.time()-t0:.1f}s answer={ans!r}")
    print("usage:", d.get("usage"))
except urllib.error.HTTPError as e:
    print(f"[FAIL] HTTP {e.code} {e.read().decode()[:200]}")
except Exception as e:
    print(f"[FAIL] {type(e).__name__}: {e}")
