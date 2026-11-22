#!/usr/bin/env python3
"""
Bridge 自检 / 压测脚本

用法:
    .venv/bin/python scripts/selftest.py            # 全部用例
    .venv/bin/python scripts/selftest.py basic      # 只跑基础
"""
from __future__ import annotations

import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent


def read_env(key: str, default: str = "") -> str:
    envf = ROOT / ".env"
    for line in envf.read_text().splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return default


BASE = f"http://127.0.0.1:{read_env('PORT', '8000') or 8000}"
KEY = read_env("BRIDGE_API_KEYS").split(",")[0].strip()


def call(path: str, payload=None, method="GET", timeout=200, headers=None):
    h = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
    if headers:
        h.update(headers)
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode()
            return r.status, body, time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), time.time() - t0
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}", time.time() - t0


def chat(content: str, session: str, timeout=200, stream=False):
    payload = {"model": "deepseek-web", "stream": stream,
               "messages": [{"role": "user", "content": content}]}
    st, body, el = call("/v1/chat/completions", payload, "POST", timeout,
                        {"X-Bridge-Session-Id": session})
    if st != 200:
        return None, body[:200], el
    try:
        d = json.loads(body)
        return d["choices"][0]["message"]["content"], None, el
    except Exception:
        return None, body[:200], el


def show(name, ans, err, el):
    if err:
        print(f"  [FAIL] {name}: {el:.1f}s  {err}")
        return False
    print(f"  [ OK ] {name}: {el:.1f}s  {str(ans)[:90].replace(chr(10), ' ')}")
    return True


def reset_worker():
    call("/api/accounts/ds-main/worker/stop", {}, "POST", 60)
    time.sleep(2)
    call("/api/accounts/ds-main/worker/start", {}, "POST", 90)
    time.sleep(4)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    ok = 0
    total = 0

    def run(name, content, session):
        nonlocal ok, total
        total += 1
        a, e, el = chat(content, session)
        ok += 1 if show(name, a, e, el) else 0

    print(f"== 健康检查 {BASE} ==")
    st, body, el = call("/api/health")
    print(f"  {st} {body[:120]}")

    print("== 基础：3 个不同 session 各一句 ==")
    run("s-A 首发", "只回答两个字：收到", "st-a")
    run("s-B 首发", "只回答两个字：明白", "st-b")
    run("s-C 首发", "只回答数字：42", "st-c")

    if mode in ("all", "reuse"):
        print("== 同 session 复用（第 2 轮）==")
        run("s-A 第2轮", "只回答两个字：继续", "st-a")
        run("s-B 第2轮", "只回答数字：7", "st-b")

    if mode in ("all", "stream"):
        print("== 流式 ==")
        st, body, el = call("/v1/chat/completions",
                            {"model": "deepseek-web", "stream": True,
                             "messages": [{"role": "user", "content": "只回答：OK"}]},
                            "POST", 200, {"X-Bridge-Session-Id": "st-stream"})
        chunk = "".join(
            json.loads(l[6:])["choices"][0]["delta"].get("content", "")
            for l in body.splitlines() if l.startswith("data: ") and "[DONE]" not in l
        )
        ok += 1 if show("stream", chunk or None, None if chunk else body[:150], el) else 0
        total += 1

    print(f"\n结果: {ok}/{total} 通过")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
