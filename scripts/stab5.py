#!/usr/bin/env python3
"""连打 5 次，验证稳定性。"""
import json, pathlib, sys, time, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
env = dict(l.split("=", 1) for l in (ROOT / ".env").read_text().splitlines()
           if "=" in l and not l.startswith("#"))
key = env["BRIDGE_API_KEYS"].split(",")[0].strip()
url = f"http://127.0.0.1:{env.get('PORT', '8000').strip()}/v1/chat/completions"

ok = 0
for i in range(1, 6):
    want = f"R{i}"
    body = json.dumps({"model": "deepseek-web", "stream": False,
                       "messages": [{"role": "user", "content": f"只输出这三个字符：{want}"}]}).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {key}"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=240) as r:
            d = json.loads(r.read().decode())
        ans = (d["choices"][0]["message"]["content"] or "").strip()
        good = want in ans
        ok += good
        print(f"#{i} {time.time()-t0:6.1f}s {'OK ' if good else 'BAD'} ans={ans[:40]!r}", flush=True)
    except Exception as e:
        detail = ""
        if hasattr(e, "read"):
            try: detail = e.read().decode()[:160]
            except Exception: pass
        print(f"#{i} {time.time()-t0:6.1f}s FAIL {type(e).__name__} {detail}", flush=True)
print(f"结果 {ok}/5", flush=True)
