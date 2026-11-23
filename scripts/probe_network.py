#!/usr/bin/env python3
"""探针：截获 DeepSeek 网页发送消息时的网络响应，看能否直接拿结构化回复。"""
import asyncio
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.async_api import async_playwright  # noqa: E402
from app.account_store import AccountStore  # noqa: E402
from app.deepseek_browser import (  # noqa: E402
    DEEPSEEK_URL, context_options_from_state, cookie_for_playwright, storage_init_script,
)

HITS = []
INTEREST = ("completion", "chat/", "api/v0", "stream", "message")


async def main():
    store = AccountStore()
    state, _ = store.load_state("ds-main")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True,
                                         args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await browser.new_context(**context_options_from_state(state))
        ctx.set_default_timeout(40_000)
        await ctx.add_cookies([cookie_for_playwright(c) for c in state.cookies])
        await ctx.add_init_script(storage_init_script(state))

        page = await ctx.new_page()

        async def on_response(resp):
            url = resp.url
            if "deepseek.com" not in url:
                return
            if not any(k in url.lower() for k in INTEREST):
                return
            ctype = (resp.headers or {}).get("content-type", "")
            HITS.append({"url": url, "status": resp.status, "ctype": ctype, "resp": resp })

        page.on("response", lambda r: asyncio.create_task(on_response(r)))

        await page.goto(DEEPSEEK_URL, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(4000)
        ta = page.locator("textarea").first
        await ta.click(timeout=8000)
        await ta.fill("只回答两个字：收到")
        await page.keyboard.press("Enter")
        print("已发送，等待 15s…")
        await page.wait_for_timeout(15000)

        print(f"\n=== 命中 {len(HITS)} 个候选请求 ===")
        for i, h in enumerate(HITS[:12], 1):
            print(f"\n--- #{i} {h['status']} {h['ctype']} ---")
            print(h["url"][:160])
            try:
                body = await h["resp"].text()
                print(f"bodyLen={len(body)}")
                print(body[:1200].replace("\n", "\\n"))
            except Exception as exc:
                print(f"读不了 body: {type(exc).__name__}: {exc}")

        await page.screenshot(path=str(ROOT / "logs" / "probe_net.png"))
        await browser.close()


if __name__ == "__main__":
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",
                          str(pathlib.Path.home() / "Library/Application Support/cn.org.hermesagent.desktop"
                              / "runtime/hermes-home/cache/ms-playwright"))
    asyncio.run(main())
