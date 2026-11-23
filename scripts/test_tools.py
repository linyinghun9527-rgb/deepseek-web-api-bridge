#!/usr/bin/env python3
"""验证 Bridge 是否真的支持 OpenAI tools / tool_calls。"""
import json, pathlib, sys, time, urllib.request, urllib.error

ROOT = pathlib.Path(__file__).resolve().parent.parent
env = dict(l.split("=", 1) for l in (ROOT / ".env").read_text().splitlines()
           if "=" in l and not l.startswith("#"))
key = env["BRIDGE_API_KEYS"].split(",")[0].strip()
base = f"http://127.0.0.1:{env.get('PORT', '8000').strip()}"

tools = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "查询指定城市的天气",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "城市名"}},
            "required": ["city"],
        },
    },
}]

payload = {
    "model": "deepseek-web",
    "stream": False,
    "messages": [
        {"role": "user", "content": "帮我查一下北京的天气，用工具查。"},
    ],
    "tools": tools,
}

req = urllib.request.Request(base + "/v1/chat/completions",
                             data=json.dumps(payload).encode(),
                             headers={"Content-Type": "application/json",
                                      "Authorization": f"Bearer {key}"},
                             method="POST")
t0 = time.time()
try:
    with urllib.request.urlopen(req, timeout=300) as r:
        body = r.read().decode()
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print("HTTP", e.code)
d = json.loads(body)
msg = (d.get("choices") or [{}])[0].get("message", {})
print(f"耗时 {time.time()-t0:.1f}s")
print("finish_reason:", (d.get("choices") or [{}])[0].get("finish_reason"))
print("tool_calls:", json.dumps(msg.get("tool_calls"), ensure_ascii=False))
print("content:", repr((msg.get("content") or "")[:200]))
