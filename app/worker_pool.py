from __future__ import annotations

import asyncio
import time
from app.account_store import AccountStore
from app.deepseek_worker import DeepSeekWorker
from app.runtime_settings import runtime_store
from app.schemas import WorkerStatusResponse


class WorkerPool:
    def __init__(self) -> None:
        self.store = AccountStore()
        self.workers: dict[str, DeepSeekWorker] = {}
        self._assign_lock = asyncio.Lock()
        self._health_task: asyncio.Task | None = None
        # 修复(本地): 记录每个 worker 进入 busy 的时刻，用于卡死检测
        self._busy_since: dict[str, float] = {}

    def get_or_create(self, account_id: str) -> DeepSeekWorker:
        if account_id not in self.workers:
            self.workers[account_id] = DeepSeekWorker(account_id)
        return self.workers[account_id]

    async def start_worker(self, account_id: str) -> WorkerStatusResponse:
        state, _ = self.store.load_state(account_id)
        return await self.get_or_create(account_id).start(state)

    async def stop_worker(self, account_id: str) -> WorkerStatusResponse:
        return await self.get_or_create(account_id).stop()

    async def restart_worker(self, account_id: str) -> WorkerStatusResponse:
        state, _ = self.store.load_state(account_id)
        return await self.get_or_create(account_id).restart(state)

    async def reset_conversation(self, account_id: str) -> WorkerStatusResponse:
        state, _ = self.store.load_state(account_id)
        return await self.get_or_create(account_id).reset_conversation(state)

    async def dom_debug(self, account_id: str) -> dict:
        state, _ = self.store.load_state(account_id)
        return await self.get_or_create(account_id).dom_debug(state)

    async def dom_probe(self, account_id: str, prompt: str, *, new_conversation: bool = False, timeout_ms: int = 120_000) -> dict:
        state, _ = self.store.load_state(account_id)
        return await self.get_or_create(account_id).dom_probe(
            state,
            prompt,
            new_conversation=new_conversation,
            timeout_ms=timeout_ms,
        )

    async def status(self, account_id: str) -> WorkerStatusResponse:
        return await self.get_or_create(account_id).status()

    async def fleet_status(self) -> list[WorkerStatusResponse]:
        out = []
        for acc in self.store.list_accounts():
            out.append(await self.status(acc.accountId))
        return out

    async def start_all(self) -> None:
        for acc in self.store.list_accounts():
            if not acc.enabled:
                continue
            try:
                await self.start_worker(acc.accountId)
            except Exception:
                pass

    async def ensure_health_task(self) -> None:
        if self._health_task and not self._health_task.done():
            return
        self._health_task = asyncio.create_task(self._health_loop())

    async def _health_loop(self) -> None:
        while True:
            rt = runtime_store.get()
            try:
                await asyncio.sleep(max(5, rt.workerHealthcheckSeconds))
                for acc in self.store.list_accounts():
                    if not acc.enabled:
                        continue
                    worker = self.get_or_create(acc.accountId)
                    status = await worker.status()

                    # 修复(本地): 卡死看门狗。ask 若被卡在 Playwright 调用上，
                    # _lock 和 _busy 会永久不释放，后续请求全部排队。
                    # 超过硬超时仍未结束就强制重建浏览器。
                    if status.busy:
                        t0 = self._busy_since.setdefault(acc.accountId, time.monotonic())
                        stall_limit = rt.workerHardTimeoutMs / 1000 + 30
                        if time.monotonic() - t0 > stall_limit:
                            self._busy_since.pop(acc.accountId, None)
                            try:
                                state, _ = self.store.load_state(acc.accountId)
                                await worker.force_recover(state)
                            except Exception:
                                pass
                        continue

                    self._busy_since.pop(acc.accountId, None)
                    if rt.autoStartWorker and not status.running:
                        try:
                            await self.start_worker(acc.accountId)
                        except Exception:
                            pass
            except asyncio.CancelledError:
                break
            except Exception:
                continue

    async def pick_account(self, preferred_account_id: str | None = None) -> str:
        rt = runtime_store.get()
        start = time.monotonic()

        while True:
            async with self._assign_lock:
                if preferred_account_id:
                    acc = self.store.load_meta(preferred_account_id)
                    if not acc.enabled:
                        raise RuntimeError(f"账号 {preferred_account_id} 已停用。")
                    worker = self.get_or_create(preferred_account_id)
                    status = await worker.status()
                    if not status.running and rt.autoStartWorker:
                        try:
                            await self.start_worker(preferred_account_id)
                            status = await worker.status()
                        except Exception:
                            pass
                    if worker.reserve():
                        return preferred_account_id

                else:
                    candidates = []
                    for acc in self.store.list_accounts():
                        if not acc.enabled:
                            continue
                        worker = self.get_or_create(acc.accountId)
                        status = await worker.status()
                        if not status.running and rt.autoStartWorker:
                            try:
                                await self.start_worker(acc.accountId)
                                status = await worker.status()
                            except Exception:
                                pass
                        if status.running and not status.busy and not status.reserved:
                            score = acc.priority * 1000 + acc.weight * 10 - status.consecutiveFailures * 100 - status.restartCount
                            candidates.append((score, acc.accountId, worker))
                    if candidates:
                        candidates.sort(reverse=True, key=lambda x: x[0])
                        _, account_id, worker = candidates[0]
                        if worker.reserve():
                            return account_id

            if time.monotonic() - start > rt.schedulerWaitForIdleSeconds:
                raise TimeoutError("等待可用 Worker 超时。")
            await asyncio.sleep(0.5)

    def release_account(self, account_id: str | None) -> None:
        if account_id and account_id in self.workers:
            self.workers[account_id].release()


pool = WorkerPool()
