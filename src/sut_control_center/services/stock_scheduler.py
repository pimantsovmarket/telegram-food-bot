from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from .stock_sync import StockCatalogSource, StockSyncResult, sync_stocks


logger = logging.getLogger(__name__)
StockSyncRunner = Callable[
    [sessionmaker[Session], int, StockCatalogSource],
    Awaitable[StockSyncResult],
]


class StockSyncScheduler:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        cabinet_id: int,
        source: StockCatalogSource,
        *,
        interval_minutes: float = 15,
        runner: StockSyncRunner = sync_stocks,
    ) -> None:
        if interval_minutes <= 0:
            raise ValueError("Stock sync interval must be positive")
        self.session_factory = session_factory
        self.cabinet_id = cabinet_id
        self.source = source
        self.interval_seconds = interval_minutes * 60
        self._runner = runner
        self._run_lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self, _application: Any = None) -> None:
        if self.running:
            return
        await self.run_once()
        self._task = asyncio.create_task(self._periodic_loop(), name="stock-sync-scheduler")

    async def stop(self, _application: Any = None) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def run_once(self) -> bool:
        if self._run_lock.locked():
            logger.info("Stock sync skipped because another run is active")
            return False
        async with self._run_lock:
            try:
                result = await self._runner(self.session_factory, self.cabinet_id, self.source)
            except Exception:
                logger.exception("Automatic stock sync failed")
                return False
            logger.info("Automatic stock sync completed: %s rows", result.rows_received)
            return True

    async def _periodic_loop(self) -> None:
        while True:
            await asyncio.sleep(self.interval_seconds)
            await self.run_once()
