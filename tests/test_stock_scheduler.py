import asyncio
from sut_control_center.services.stock_scheduler import DataSyncScheduler, JOB_ORDER


def scheduler(jobs, *, intervals=(1, 1, 1, 1)):
    return DataSyncScheduler(
        jobs,
        stock_interval_minutes=intervals[0],
        sales_interval_minutes=intervals[1],
        returns_interval_minutes=intervals[2],
        finance_interval_minutes=intervals[3],
    )


def test_startup_and_periodic_sync():
    async def scenario():
        calls = []

        def job(name):
            async def run():
                calls.append(name)
            return run

        service = scheduler({name: job(name) for name in JOB_ORDER}, intervals=(0.001, 0.0015, 0.002, 0.0025))
        await service.start()
        assert calls == list(JOB_ORDER) and service.running
        await asyncio.sleep(0.17)
        assert calls.count("stocks") >= 3
        assert calls.count("postings") >= 2
        assert calls.count("returns") >= 2
        assert calls.count("finance") >= 2
        await service.stop()
        assert not service.running

    asyncio.run(scenario())


def test_overlapping_sync_is_skipped():
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def stock_job():
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()

        async def no_op():
            return None

        jobs = {name: no_op for name in JOB_ORDER}
        jobs["stocks"] = stock_job
        service = scheduler(jobs)
        first = asyncio.create_task(service.run_once("stocks"))
        await started.wait()
        assert await service.run_once("stocks") is False
        assert await service.run_once("returns") is True
        release.set()
        assert await first is True
        assert calls == 1

    asyncio.run(scenario())


def test_api_error_does_not_stop_periodic_scheduler():
    async def scenario():
        calls = 0

        async def stock_job():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("API unavailable")

        successful = []

        def job(name):
            async def run():
                successful.append(name)
            return run

        jobs = {name: job(name) for name in JOB_ORDER}
        jobs["stocks"] = stock_job
        service = scheduler(jobs, intervals=(0.001, 0.001, 0.001, 0.001))
        await service.start()
        assert service.running
        await asyncio.sleep(0.075)
        assert calls >= 2 and service.running
        assert set(successful) == {"postings", "returns", "finance"}
        await service.stop()

    asyncio.run(scenario())


def test_shutdown_cancels_waiting_task():
    async def scenario():
        async def runner():
            return None

        service = scheduler({name: runner for name in JOB_ORDER})
        await service.start()
        tasks = tuple(service._tasks.values())
        await service.stop()
        assert all(task.cancelled() for task in tasks)

    asyncio.run(scenario())


def test_single_scheduler_owns_exactly_one_stock_job():
    async def runner():
        return None

    service = scheduler({name: runner for name in JOB_ORDER})
    assert tuple(service.jobs).count("stocks") == 1
