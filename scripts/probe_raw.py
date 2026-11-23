#!/usr/bin/env python3
"""探针3：注入 fetch 钩子，抓 /api/v0/chat/completion 的原始 SSE 行。"""
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

HOOK = r"""
(() => {
  window.__DS_RAW = [];
  const of = window.fetch;
  window.fetch = async function(input, init) {
    const url = (typeof input === 'string') ? input : ((input && input.url) || '');
    const resp = await of.apply(this, arguments);
    if (url.indexOf('/api/v0/chat/completion') >= 0) {
      try {
        const c = resp.clone();
        (async () => {
          const rd = c.body.getReader();
          const dec = new TextDecoder();
          let buf = '';
          while (true) {
            const r = await rd.read();
            if (r.done) break;
            buf += dec.decode(r.value, {stream: true});
            let i;
            while ((i = buf.indexOf('\n')) >= 0) {
              const line = buf.slice(0, i).trim();
              buf = buf.slice(i + 1);
              if (line && window.__DS_RAW.length < 40) window.__DS_RAW.push(line.slice(0, 600));
            }
          }
          window.__DS_RAW.push('<<STREAM_END>>');
        })();
      } catch (e) { window.__DS_RAW.push('HOOK_ERR ' + e); }
    }
    return resp;
  };
})();
"""


async def main():
    state, _ = AccountStore().load_state("ds-main")
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await b.new_context(**context_options_from_state(state))
        await ctx.add_cookies([cookie_for_playwright(c) for c in state.cookies])
        await ctx.add_init_script(storage_init_script(state))
        await ctx.add_init_script(HOOK)
        page = await ctx.new_page()
        await page.goto(DEEPSEEK_URL, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(4000)
        ta = page.locator("textarea").first
        await ta.click(timeout=10000)
        await ta.fill("只回答两个字：收到")
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(16000)
        raw = await page.evaluate("() => window.__DS_RAW || []")
        print(f"=== 捕获 {len(raw)} 行 ===")
        for line in raw[:30]:
            print(line[:500])
        await b.close()

if __name__ == "__main__":
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",
        str(pathlib.Path.home() / "Library/Application Support/cn.org.hermesagent.desktop"
            / "runtime/hermes-home/cache/ms-playwright"))
    asyncio.run(main())
