#!/usr/bin/env python3
"""最小实验：headless 多 page 是否渲染"""
import asyncio
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.async_api import async_playwright  # noqa: E402
from app.account_store import AccountStore  # noqa: E402
from app.deepseek_browser import (  # noqa: E402
    DEEPSEEK_URL, context_options_from_state, cookie_for_playwright, storage_init_script,
)

PROBE = """
() => {
  const ta = document.querySelector('textarea');
  const r = ta ? ta.getBoundingClientRect() : null;
  return {
    bodyLen: (document.body && document.body.innerText || '').length,
    taExists: !!ta,
    taBox: r ? {w: Math.round(r.width), h: Math.round(r.height)} : null,
    title: document.title,
    url: location.href,
    vis: document.visibilityState,
  };
}
"""


async def main():
    store = AccountStore()
    state, _ = store.load_state("ds-main")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await browser.new_context(**context_options_from_state(state))
        ctx.set_default_timeout(30_000)
        await ctx.add_cookies([cookie_for_playwright(c) for c in state.cookies])
        await ctx.add_init_script(storage_init_script(state))

        for i in (1, 2, 3):
            page = await ctx.new_page()
            page.set_default_timeout(30_000)
            await page.goto(DEEPSEEK_URL, wait_until="domcontentloaded", timeout=45_000)
            await page.wait_for_timeout(4000)
            print(f"page{i} (未 bring_to_front):", await page.evaluate(PROBE))
            await page.bring_to_front()
            await page.wait_for_timeout(2000)
            print(f"page{i} (bring_to_front 后):", await page.evaluate(PROBE))
            print("  pages in ctx:", len(ctx.pages))
        await browser.close()


if __name__ == "__main__":
    import os
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",
                          str(pathlib.Path.home() / "Library/Application Support/cn.org.hermesagent.desktop"
                              / "runtime/hermes-home/cache/ms-playwright"))
    asyncio.run(main())
