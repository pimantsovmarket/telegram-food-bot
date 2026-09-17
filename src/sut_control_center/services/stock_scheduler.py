from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

logger = logging.getLogger(__name__)
SyncJob = Callable[[], Awaitable[Any]]
JOB_ORDER = ("stocks", "postings", "returns", "finance")


class DataSyncScheduler:
    def __init__(
        self,
        jobs: dict[str, SyncJob],
        *,
        stock_interval_minutes: float = 15,
        sales_interval_minutes: float = 15,
        returns_interval_minutes: float = 30,
        finance_interval_minutes: float = 60,
    ) -> None:
        if set(jobs) != set(JOB_ORDER):
            raise ValueError("Data sync scheduler requires stocks, postings, returns and finance jobs")
        intervals = {
            "stocks": stock_interval_minutes,
            "postings": sales_interval_minutes,
            "returns": returns_interval_minutes,
            "finance": finance_interval_minutes,
        }
        if any(value <= 0 for value in intervals.values()):
            raise ValueError("Data sync intervals must be positive")
        self.jobs = jobs
        self.interval_seconds = {name: value * 60 for name, value in intervals.items()}
        self._run_locks = {name: asyncio.Lock() for name in JOB_ORDER}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    @property
    def running(self) -> bool:
        return bool(self._tasks) and all(not task.done() for task in self._tasks.values())

    async def start(self, _application: Any = None) -> None:
        if self.running:
            return
        for name in JOB_ORDER:
            await self.run_once(name)
        self._tasks = {
            name: asyncio.create_task(self._periodic_loop(name), name=f"{name}-sync-scheduler")
            for name in JOB_ORDER
        }

    async def stop(self, _application: Any = None) -> None:
        tasks = tuple(self._tasks.values())
        self._tasks = {}
        if not tasks:
            return
        for task in tasks:
            task.cancel()
        with suppress(asyncio.CancelledError):
            await asyncio.gather(*tasks)

    async def run_once(self, name: str) -> bool:
        if name not in self.jobs:
            raise ValueError(f"Unknown sync job: {name}")
        lock = self._run_locks[name]
        if lock.locked():
            logger.info("%s sync skipped because another run is active", name)
            return False
        async with lock:
            try:
                await self.jobs[name]()
            except Exception:
                logger.exception("Automatic %s sync failed", name)
                return False
            logger.info("Automatic %s sync completed", name)
            return True

    async def _periodic_loop(self, name: str) -> None:
        while True:
            await asyncio.sleep(self.interval_seconds[name])
            await self.run_once(name)
