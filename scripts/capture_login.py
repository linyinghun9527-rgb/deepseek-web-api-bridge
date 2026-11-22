#!/usr/bin/env python3
"""
DeepSeek 登录态抓取 + 自动导入 Bridge

用法:
    .venv/bin/python scripts/capture_login.py                # 打开可见浏览器，扫码登录后自动抓取并导入
    .venv/bin/python scripts/capture_login.py --account-id ds-1 --display-name "我的DeepSeek"
    .venv/bin/python scripts/capture_login.py --no-import     # 只抓取到 data/logins/*.json，不导入

说明:
- 浏览器用户目录持久化在 data/browser-profile，下次再跑不用重复登录。
- 抓到的最原始 JSON 只写到 data/logins/（.gitignore 已排除），导入成功后默认删除原始明文副本，
  实际存储由 Bridge 用 Fernet 加密。
- 终端不会打印 cookie / token 的值。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.request
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEEPSEEK_URL = "https://chat.deepseek.com/"
PROFILE_DIR = ROOT / "data" / "browser-profile"
OUT_DIR = ROOT / "data" / "logins"


def read_env(key: str, default: str = "") -> str:
    envf = ROOT / ".env"
    if not envf.exists():
        return default
    for line in envf.read_text().splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return default


LOGIN_PROBE = """
() => {
  const out = {token: false, composer: false, url: location.href, title: document.title};
  try {
    const raw = localStorage.getItem('userToken');
    if (raw) {
      try { out.token = !!(JSON.parse(raw) || {}).value; } catch (e) { out.token = raw.length > 20; }
    }
  } catch (e) {}
  try {
    out.composer = !!document.querySelector('textarea, [contenteditable="true"]');
  } catch (e) {}
  return out;
}
"""

STORAGE_DUMP = """
() => {
  const dump = (s) => { const o = {}; for (let i = 0; i < s.length; i++) { const k = s.key(i); o[k] = s.getItem(k); } return o; };
  return {
    local: dump(localStorage),
    session: dump(sessionStorage),
    env: {
      navigator: { userAgent: navigator.userAgent, language: navigator.language },
      intl: { locale: navigator.language, timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone },
      screen: { width: screen.width, height: screen.height, devicePixelRatio: window.devicePixelRatio || 1 }
    }
  };
}
"""


def post_json(url: str, payload: dict, api_key: str) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


async def run(args) -> int:
    from playwright.async_api import async_playwright

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            no_viewport=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        print(f"[1/4] 打开 {DEEPSEEK_URL}")
        try:
            await page.goto(DEEPSEEK_URL, wait_until="domcontentloaded", timeout=60_000)
        except Exception as exc:
            print(f"     页面加载告警: {type(exc).__name__}: {exc}")

        probe = None
        deadline = time.time() + args.timeout
        last_note = 0
        print("[2/4] 等待登录：若弹出登录框，请用手机 DeepSeek App 扫码（或手机号登录）")
        while time.time() < deadline:
            try:
                probe = await page.evaluate(LOGIN_PROBE)
            except Exception:
                probe = None
            if probe and (probe.get("token") or (probe.get("composer") and "sign_in" not in probe.get("url", ""))):
                break
            if time.time() - last_note > 15:
                print(f"     仍在等待… 当前 {probe.get('url') if probe else '页面切换中'}")
                last_note = time.time()
            await page.wait_for_timeout(1500)
        else:
            print("[×] 超时未检测到登录态。窗口保留 30 秒，可继续登录后再手动重跑本脚本。")
            await page.wait_for_timeout(30_000)
            await ctx.close()
            return 2

        print("[3/4] 检测到登录态，开始抓取 cookies / localStorage")
        # 稍等一下，让页面把 user 信息写进 localStorage
        await page.wait_for_timeout(2500)
        dump = await page.evaluate(STORAGE_DUMP)
        cookies = await ctx.cookies()
        state = {
            "schemaVersion": "v21-capture",
            "capturedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "pageUrl": page.url,
            "page": {"pageUrl": page.url, "title": await page.title()},
            "env": dump.get("env", {}),
            "storage": {"local": dump.get("local", {}), "session": dump.get("session", {})},
            "headers": {},
            "cookies": cookies,
            "meta": {"capturedBy": "scripts/capture_login.py"},
        }
        ds_cookies = [c["name"] for c in cookies if "deepseek.com" in c.get("domain", "")]
        print(f"     cookies 总数 {len(cookies)}，其中 deepseek.com 域 {len(ds_cookies)} 个：{', '.join(ds_cookies)}")
        if not ds_cookies:
            print("[×] 没抓到 deepseek.com 的 cookie，登录可能没成功。")
            await ctx.close()
            return 3

        out = OUT_DIR / f"deepseek-state-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        out.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        os.chmod(out, 0o600)
        print(f"     已保存到 {out.relative_to(ROOT)} (权限 600)")

        if args.no_import:
            await ctx.close()
            print("[4/4] --no-import，跳过导入。")
            return 0

        api_key = args.api_key or read_env("BRIDGE_API_KEYS").split(",")[0].strip()
        base = f"http://127.0.0.1:{args.port}"
        payload = {
            "accountId": args.account_id,
            "displayName": args.display_name,
            "notes": "captured by capture_login.py",
            "state": state,
            "enabled": True,
            "priority": 100,
            "weight": 100,
        }
        print(f"[4/4] 导入到 {base}/api/accounts/import (accountId={args.account_id})")
        try:
            res = post_json(f"{base}/api/accounts/import", payload, api_key)
            print("     导入成功:", json.dumps(res.get("account", {}), ensure_ascii=False))
        except Exception as exc:
            body = ""
            if hasattr(exc, "read"):
                try:
                    body = exc.read().decode()[:500]
                except Exception:
                    pass
            print(f"[×] 导入失败: {type(exc).__name__}: {exc} {body}")
            await ctx.close()
            return 4

        if args.keep_raw:
            print(f"     保留原始明文副本: {out}")
        else:
            out.unlink(missing_ok=True)
            print("     已删除原始明文副本（Bridge 内为加密存储）")

        await ctx.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account-id", default="ds-main")
    ap.add_argument("--display-name", default="主账号")
    ap.add_argument("--port", type=int, default=int(read_env("PORT", "8000") or 8000))
    ap.add_argument("--api-key", default="")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--no-import", action="store_true")
    ap.add_argument("--keep-raw", action="store_true")
    args = ap.parse_args()
    import asyncio

    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
