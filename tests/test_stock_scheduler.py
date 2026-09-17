import asyncio
from types import SimpleNamespace

from sut_control_center.services.stock_scheduler import StockSyncScheduler


def scheduler(runner, *, interval_minutes=1):
    return StockSyncScheduler(
        SimpleNamespace(),
        1,
        SimpleNamespace(),
        interval_minutes=interval_minutes,
        runner=runner,
    )


def test_startup_and_periodic_sync():
    async def scenario():
        calls = 0

        async def runner(*_args):
            nonlocal calls
            calls += 1
            return SimpleNamespace(rows_received=1)

        service = scheduler(runner, interval_minutes=0.001)
        await service.start()
        assert calls == 1 and service.running
        await asyncio.sleep(0.075)
        assert calls >= 2
        await service.stop()
        assert not service.running

    asyncio.run(scenario())


def test_overlapping_sync_is_skipped():
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def runner(*_args):
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return SimpleNamespace(rows_received=1)

        service = scheduler(runner)
        first = asyncio.create_task(service.run_once())
        await started.wait()
        assert await service.run_once() is False
        release.set()
        assert await first is True
        assert calls == 1

    asyncio.run(scenario())


def test_api_error_does_not_stop_periodic_scheduler():
    async def scenario():
        calls = 0

        async def runner(*_args):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("API unavailable")
            return SimpleNamespace(rows_received=1)

        service = scheduler(runner, interval_minutes=0.001)
        await service.start()
        assert service.running
        await asyncio.sleep(0.075)
        assert calls >= 2 and service.running
        await service.stop()

    asyncio.run(scenario())


def test_shutdown_cancels_waiting_task():
    async def scenario():
        async def runner(*_args):
            return SimpleNamespace(rows_received=0)

        service = scheduler(runner)
        await service.start()
        task = service._task
        await service.stop()
        assert task is not None and task.cancelled()

    asyncio.run(scenario())
