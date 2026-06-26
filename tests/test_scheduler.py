from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from evemarket.config import Config
from evemarket.scheduler import build_scheduler, run_orders_job, run_prices_job


def test_build_scheduler_registers_orders_and_prices_jobs() -> None:
    sched = build_scheduler(Config(tracked_regions=[10000002]))

    jobs = {job.id: job for job in sched.get_jobs()}

    assert set(jobs) == {"orders", "prices"}
    assert jobs["orders"].trigger.interval == timedelta(minutes=5)
    assert jobs["prices"].trigger.interval == timedelta(minutes=60)


def test_build_scheduler_uses_custom_intervals() -> None:
    sched = build_scheduler(
        Config(tracked_regions=[10000002]),
        orders_interval_minutes=7,
        prices_interval_minutes=90,
    )

    jobs = {job.id: job for job in sched.get_jobs()}

    assert jobs["orders"].trigger.interval == timedelta(minutes=7)
    assert jobs["prices"].trigger.interval == timedelta(minutes=90)


def test_run_prices_job_returns_ingest_result() -> None:
    calls = []
    expected = SimpleNamespace(run_id="prices-run", price_count=3, status="success")

    async def fake_ingest(client, config):
        calls.append((client, config))
        return expected

    config = Config()

    result = run_prices_job(config, ingest=fake_ingest)

    assert result is expected
    assert len(calls) == 1
    assert calls[0][1] is config


def test_run_prices_job_swallows_ingest_exception() -> None:
    async def fake_ingest(client, config):
        raise RuntimeError("boom")

    assert run_prices_job(Config(), ingest=fake_ingest) is None


def test_run_orders_job_runs_once_per_tracked_region() -> None:
    calls = []

    async def fake_ingest(client, config, region_id):
        calls.append((client, config, region_id))
        return SimpleNamespace(
            run_id=f"orders-{region_id}",
            region_id=region_id,
            order_count=10,
            status="success",
        )

    config = Config(tracked_regions=[10000002, 10000043])

    results = run_orders_job(config, ingest=fake_ingest)

    assert [result.region_id for result in results] == [10000002, 10000043]
    assert [call[2] for call in calls] == [10000002, 10000043]
    assert all(call[1] is config for call in calls)


def test_run_orders_job_swallows_ingest_exception() -> None:
    async def fake_ingest(client, config, region_id):
        raise RuntimeError("boom")

    assert run_orders_job(Config(tracked_regions=[10000002]), ingest=fake_ingest) == []
