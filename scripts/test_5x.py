#!/usr/bin/env python3
"""连续 5 次单轮请求，测稳定性（不受干扰版）。"""
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

ok = 0
for i in range(1, 6):
    payload = {"model": "deepseek-web", "stream": False,
               "messages": [{"role": "user", "content": f"只回答数字：{i}"}]}
    req = urllib.request.Request(base + "/v1/chat/completions",
                                data=json.dumps(payload).encode(),
                                headers={"Content-Type": "application/json",
                                         "Authorization": f"Bearer {key}"},
                                method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            body = r.read().decode()
        d = json.loads(body)
        ans = (d.get("choices") or [{}])[0].get("message", {}).get("content")
        el = time.time() - t0
        flag = "OK " if ans else "EMPTY"
        if ans:
            ok += 1
        print(f"[{flag}] #{i} {el:6.1f}s answer={ans!r}")
    except urllib.error.HTTPError as e:
        print(f"[FAIL] #{i} {time.time()-t0:6.1f}s HTTP {e.code} {e.read().decode()[:150]}")
    except Exception as e:
        print(f"[FAIL] #{i} {time.time()-t0:6.1f}s {type(e).__name__}: {e}")
    sys_pause = 1.5
    time.sleep(sys_pause)

print(f"\n结果: {ok}/5")
