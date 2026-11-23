#!/usr/bin/env python3
"""探针：抓 DeepSeek 网页自身的接口响应，判断能否走网络层取回复。"""
import asyncio
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from playwright.async_api import async_playwright
from app.account_store import AccountStore
from app.deepseek_browser import (DEEPSEEK_URL, context_options_from_state,
                                  cookie_for_playwright, storage_init_script)

seen = []


async def main():
    state, _ = AccountStore().load_state("ds-main")
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await b.new_context(**context_options_from_state(state))
        await ctx.add_cookies([cookie_for_playwright(c) for c in state.cookies])
        await ctx.add_init_script(storage_init_script(state))
        page = await ctx.new_page()

        async def on_resp(resp):
            u = resp.url
            if any(x in u for x in ("/api/", "completion", "chat")):
                seen.append((resp.status, u[:160], resp.headers.get("content-type", "")[:60]))

        page.on("response", on_resp)
        await page.goto(DEEPSEEK_URL, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(4000)
        ta = page.locator("textarea").first
        await ta.click(timeout=10000)
        await ta.fill("只回答两个字：收到")
        print("已填入，准备回车")
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(15000)
        print("=== 捕获到的接口 ===")
        for s, u, c in seen[-25:]:
            print(f"{s} {c} {u}")
        await b.close()

if __name__ == "__main__":
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",
        str(pathlib.Path.home() / "Library/Application Support/cn.org.hermesagent.desktop"
            / "runtime/hermes-home/cache/ms-playwright"))
    asyncio.run(main())
