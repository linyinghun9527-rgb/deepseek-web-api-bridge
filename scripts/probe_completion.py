#!/usr/bin/env python3
"""探针2：只截获 /api/v0/chat/completion 的响应体，看结构。"""
import asyncio
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from playwright.async_api import async_playwright
from app.account_store import AccountStore
from app.deepseek_browser import (DEEPSEEK_URL, context_options_from_state,
                                  cookie_for_playwright, storage_init_script)

OUT = ROOT / "logs" / "completion_body.txt"


async def main():
    state, _ = AccountStore().load_state("ds-main")
    got = []

    async def on_resp(resp):
        if "chat/completion" in resp.url:
            try:
                body = await resp.text()
                got.append((resp.status, body))
                print(f"命中 completion: status={resp.status} len={len(body)}")
            except Exception as exc:
                print("读body失败:", type(exc).__name__, exc)

    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await b.new_context(**context_options_from_state(state))
        await ctx.add_cookies([cookie_for_playwright(c) for c in state.cookies])
        await ctx.add_init_script(storage_init_script(state))
        page = await ctx.new_page()
        page.on("response", lambda r: asyncio.create_task(on_resp(r)))
        await page.goto(DEEPSEEK_URL, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(4000)
        ta = page.locator("textarea").first
        await ta.click(timeout=10000)
        await ta.fill("只回答两个字：收到")
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(18000)
        if got:
            OUT.write_text(got[-1][1])
            print("已保存到", OUT)
            print("首 900 字符:")
            print(got[-1][1][:900])
        else:
            print("没截到 completion 响应")
        await b.close()

if __name__ == "__main__":
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",
        str(pathlib.Path.home() / "Library/Application Support/cn.org.hermesagent.desktop"
            / "runtime/hermes-home/cache/ms-playwright"))
    asyncio.run(main())
