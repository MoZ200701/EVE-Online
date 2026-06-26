"""Recurring ingest job scheduling."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler

from evemarket.config import Config
from evemarket.esi.client import ESIClient
from evemarket.ingest.orders import IngestResult, ingest_orders
from evemarket.ingest.prices import PricesIngestResult, ingest_prices

LOGGER = logging.getLogger(__name__)


def run_prices_job(
    config: Config,
    *,
    ingest: Any = ingest_prices,
) -> PricesIngestResult | None:
    """Run one global prices ingest for APScheduler."""

    try:

        async def _run() -> PricesIngestResult:
            async with ESIClient(config=config) as client:
                return await ingest(client, config)

        result = asyncio.run(_run())
        LOGGER.info("prices job ok run_id=%s count=%s", result.run_id, result.price_count)
        return result
    except Exception:
        LOGGER.exception("prices job failed")
        return None


def run_orders_job(
    config: Config,
    *,
    ingest: Any = ingest_orders,
) -> list[IngestResult]:
    """Run one order snapshot ingest per tracked region for APScheduler."""

    try:

        async def _run() -> list[IngestResult]:
            results = []
            async with ESIClient(config=config) as client:
                for region in config.tracked_regions:
                    results.append(await ingest(client, config, region))
            return results

        results = asyncio.run(_run())
        LOGGER.info("orders job ok regions=%s", [r.region_id for r in results])
        return results
    except Exception:
        LOGGER.exception("orders job failed")
        return []


def build_scheduler(
    config: Config,
    *,
    scheduler: BlockingScheduler | None = None,
    orders_interval_minutes: int = 5,
    prices_interval_minutes: int = 60,
) -> BlockingScheduler:
    """Build a blocking scheduler with recurring ingest jobs registered."""

    sched = scheduler or BlockingScheduler(timezone=pytz.utc)
    sched.add_job(
        run_orders_job,
        "interval",
        minutes=orders_interval_minutes,
        args=[config],
        id="orders",
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )
    sched.add_job(
        run_prices_job,
        "interval",
        minutes=prices_interval_minutes,
        args=[config],
        id="prices",
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )
    return sched
