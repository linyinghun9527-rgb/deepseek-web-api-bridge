#!/usr/bin/env python3
"""单页探针：登录态是否有效 + 页面是否渲染 + 消息节点实际长什么样。"""
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

PROBE = """
() => {
  const txt = (document.body && document.body.innerText) || '';
  const cnt = (s) => document.querySelectorAll(s).length;
  return {
    url: location.href,
    title: document.title,
    bodyLen: txt.length,
    head: txt.slice(0, 400),
    textarea: cnt('textarea'),
    dsMarkdown: cnt('.ds-markdown'),
    markdownAny: cnt("[class*='markdown' i]"),
    assistantAttr: cnt("[class*='assistant' i]"),
    dataRoleAssist: cnt("[data-message-author-role='assistant']"),
    sides: cnt("[class*='_4f9bf79']"),
    divCount: cnt('div'),
  };
}
"""


async def main():
    store = AccountStore()
    state, _ = store.load_state("ds-main")
    print(f"state cookies={len(state.cookies)} pageUrl={getattr(state, 'pageUrl', '?')}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True,
                                         args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await browser.new_context(**context_options_from_state(state))
        ctx.set_default_timeout(40_000)
        await ctx.add_cookies([cookie_for_playwright(c) for c in state.cookies])
        await ctx.add_init_script(storage_init_script(state))

        page = await ctx.new_page()
        page.set_default_timeout(40_000)
        await page.goto(DEEPSEEK_URL, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(5000)
        print("== 首次加载 ==")
        print(json.dumps(await page.evaluate(PROBE), ensure_ascii=False, indent=2))

        # 尝试发一条，看回复节点
        try:
            ta = page.locator("textarea").first
            await ta.click(timeout=8000)
            await ta.fill("只回答两个字：收到")
            await page.keyboard.press("Enter")
            print("\n== 已发送，等 12s ==")
            for i in range(6):
                await page.wait_for_timeout(2000)
                info = await page.evaluate(PROBE)
                print(f"  t+{(i+1)*2}s bodyLen={info['bodyLen']} markdownAny={info['markdownAny']} "
                      f"assistantAttr={info['assistantAttr']}")
            final = await page.evaluate(PROBE)
            print("\n== 最终页面 ==")
            print(json.dumps(final, ensure_ascii=False, indent=2))
            # 抓一段 assistant 节点 html 结构
            html = await page.evaluate("""
            () => {
              const nodes = Array.from(document.querySelectorAll("[class*='markdown' i], [class*='assistant' i]"));
              return nodes.slice(-4).map(n => ({
                cls: n.className && n.className.toString().slice(0,120),
                tag: n.tagName,
                len: (n.innerText||'').length,
                text: (n.innerText||'').slice(0,150)
              }));
            }
            """)
            print("\n== 回复节点样本 ==")
            print(json.dumps(html, ensure_ascii=False, indent=2))
            # 存一张截图
            shot = ROOT / "logs" / "probe.png"
            await page.screenshot(path=str(shot))
            print(f"\n截图: {shot}")
        except Exception as exc:
            print(f"发送失败: {type(exc).__name__}: {exc}")
            await page.screenshot(path=str(ROOT / "logs" / "probe-fail.png"))

        await browser.close()


if __name__ == "__main__":
    _pw = pathlib.Path.home() / "Library/Application Support/cn.org.hermesagent.desktop/runtime/hermes-home/cache/ms-playwright"
    if _pw.is_dir():
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(_pw))
    asyncio.run(main())
