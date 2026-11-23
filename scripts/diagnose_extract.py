#!/usr/bin/env python3
"""
回复抓取诊断（历史脚本，仅供对照）

⚠️ 注意：本脚本内部重写了**上游旧版** `_wait_for_answer`（按 DOM order 判断新回复），
它不反映 `app/deepseek_worker.py` 现在使用的 `_wait_for_answer_v2`（取最后一个 assistant 节点）。
它跑出来「等待回复超时 / 候选=0」是修复前的现象记录，不代表当前代码状态。
当前稳定性请跑：`scripts/stab5.py` / `scripts/test_multiturn.py`。

用法: .venv/bin/python scripts/diagnose_extract.py
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.account_store import AccountStore  # noqa: E402
from app.deepseek_worker import DeepSeekWorker  # noqa: E402


class VerboseWorker(DeepSeekWorker):
    """把 _wait_for_answer 换成打印版，逻辑保持与上游一致。"""

    async def _wait_for_answer(self, page, before, prompt, *, timeout_ms):
        deadline = time.monotonic() + timeout_ms / 1000
        before_order = int((before or {}).get("maxOrder", -1))
        before_text = str((before or {}).get("text", ""))
        prompt_text = prompt.strip()
        print(f"    [diag] before: maxOrder={before_order} textLen={len(before_text)}")
        tick = 0
        last_text = ""
        last_change = time.monotonic()

        while time.monotonic() < deadline:
            await page.wait_for_timeout(700)
            tick += 1
            try:
                cands = await asyncio.wait_for(self._extract_message_candidates(page), timeout=20)
            except asyncio.TimeoutError:
                print(f"    [diag] #{tick} 提取超时")
                continue

            new = [c for c in cands if int(c.get("order") or -1) > before_order]
            print(f"    [diag] #{tick} 候选={len(cands)} 高于基线={len(new)} "
                  f"orders={[c.get('order') for c in cands][-6:]}")
            for c in new[-3:]:
                txt = str(c.get("text") or "")
                print(f"        order={c.get('order')} src={c.get('source')} len={c.get('length')} "
                      f"same_as_prompt={txt.strip() == prompt_text} preview={txt.strip()[:60]!r}")

            if new:
                explicit = [c for c in new if c.get("source") == "explicit-assistant"]
                pick = max(explicit, key=lambda c: int(c.get("length") or 0)) if explicit else None
                current = str(pick.get("text") if pick else new[-1].get("text") or "").strip()
                if current and current != before_text and current != prompt_text:
                    if current != last_text:
                        last_text = current
                        last_change = time.monotonic()
                    elif time.monotonic() - last_change >= 1.8:
                        gen = await self._is_generating(page)
                        print(f"    [diag] 稳定 1.8s, 生成中={gen} -> {'继续等' if gen else '返回'}")
                        if not gen:
                            return current
                        if time.monotonic() - last_change >= 5.0:
                            return current

        if last_text:
            return last_text
        raise TimeoutError("等待回复超时。")


async def main():
    store = AccountStore()
    state, _ = store.load_state("ds-main")
    w = VerboseWorker("ds-main")
    cases = [
        ("sess-a1", "只回答：A"),
        ("sess-a2", "只回答：B"),
        ("sess-a2", "只回答：C"),
        ("sess-a1", "只回答：D"),
    ]
    try:
        for i, (sid, prompt) in enumerate(cases, 1):
            print(f"\n===== 第 {i} 次提问 session={sid}: {prompt} =====")
            t0 = time.monotonic()
            try:
                r = await w.ask(state, prompt, new_conversation=True,
                                timeout_ms=45_000, session_id=sid)
                print(f"  结果 ok={r.ok} {time.monotonic()-t0:.1f}s answer={str(r.answer)[:80]!r}")
                print(f"  message={r.message}")
            except Exception as exc:
                print(f"  异常 {type(exc).__name__}: {exc} ({time.monotonic()-t0:.1f}s)")
    finally:
        await w.stop()


if __name__ == "__main__":
    import os
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",
                          str(pathlib.Path.home() / "Library/Application Support/cn.org.hermesagent.desktop"
                              / "runtime/hermes-home/cache/ms-playwright"))
    asyncio.run(main())
