#!/usr/bin/env python3
"""多轮上下文 + 连续请求稳定性测试（模拟真实 Agent 客户端）"""
import json
import pathlib
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent


def env(key, default=""):
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return default


BASE = f"http://127.0.0.1:{env('PORT', '8000') or 8000}"
KEY = env("BRIDGE_API_KEYS").split(",")[0].strip()


def post(payload, headers=None, timeout=400):
    h = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                data=json.dumps(payload).encode(), headers=h, method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode(), time.time() - t0, None
    except Exception as e:
        body = ""
        if hasattr(e, "read"):
            try:
                body = e.read().decode()[:200]
            except Exception:
                pass
        return None, time.time() - t0, f"{type(e).__name__}: {e} {body}"


def chat(messages, session="agent-s1"):
    body, el, err = post({"model": "deepseek-web", "stream": False, "messages": messages},
                         {"X-Bridge-Session-Id": session})
    if err:
        return None, el, err
    d = json.loads(body)
    return d["choices"][0]["message"]["content"], el, None


def main():
    ok = 0
    total = 0

    print("== 等待 worker 空闲（避免上一个残留 job 干扰）==")
    for _ in range(60):
        try:
            req = urllib.request.Request(BASE + "/api/workers/status",
                                         headers={"Authorization": f"Bearer {KEY}"})
            with urllib.request.urlopen(req, timeout=10) as r:
                w = json.loads(r.read().decode())["workers"][0]
            if not w["busy"]:
                print(f"  空闲，restartCount={w['restartCount']} err={w['lastError']}")
                break
        except Exception:
            pass
        time.sleep(2)
    else:
        print("  [警告] worker 一直 busy，测试结果可能受干扰")

    print("== 用例1: 多轮上下文（历史靠请求体传递）==")
    history = [
        {"role": "user", "content": "记住暗号：蓝鲸42"},
        {"role": "assistant", "content": "好的，暗号是蓝鲸42。"},
        {"role": "user", "content": "暗号是什么？只回答暗号本身"},
    ]
    ans, el, err = chat(history)
    total += 1
    if err or not ans or "蓝鲸" not in ans:
        print(f"  [FAIL] {el:.1f}s {err or ans}")
    else:
        print(f"  [ OK ] {el:.1f}s {ans.strip()[:60]}")
        ok += 1

    print("== 用例2: 连续 3 次请求（每次新对话）==")
    for i, q in enumerate(["只回答：A", "只回答：B", "只回答：C"], 1):
        ans, el, err = chat([{"role": "user", "content": q}], session="agent-s2")
        total += 1
        if err or not ans:
            print(f"  [FAIL] 第{i}次 {el:.1f}s {err or '空回复'}")
        else:
            print(f"  [ OK ] 第{i}次 {el:.1f}s {ans.strip()[:40]}")
            ok += 1

    print("== 用例3: 流式（完整读完，不截断）==")
    body, el, err = post({"model": "deepseek-web", "stream": True,
                          "messages": [{"role": "user", "content": "只回答：STREAM-OK"}]},
                         {"X-Bridge-Session-Id": "agent-s3"})
    total += 1
    if err:
        print(f"  [FAIL] {el:.1f}s {err}")
    else:
        text = "".join(
            json.loads(l[6:])["choices"][0]["delta"].get("content", "")
            for l in body.splitlines() if l.startswith("data: ") and "[DONE]" not in l
        )
        print(f"  [ OK ] {el:.1f}s {text.strip()[:60]}")
        ok += 1

    print(f"\n结果: {ok}/{total} 通过")
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
