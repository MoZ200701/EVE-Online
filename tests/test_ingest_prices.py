from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import duckdb
import httpx
import pytest

from evemarket.config import Config
from evemarket.esi.client import ESIClient, ESIError
from evemarket.ingest.prices import ingest_prices


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 6, 26, 12, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value


def esi_headers(clock: Clock) -> dict[str, str]:
    return {
        "Expires": format_datetime(clock() + timedelta(minutes=5)),
        "X-ESI-Error-Limit-Remain": "100",
        "X-ESI-Error-Limit-Reset": "1",
    }


def prices_payload() -> list[dict]:
    return [
        {"type_id": 18, "adjusted_price": 33.248, "average_price": 30.02},
        {"type_id": 34, "adjusted_price": 5.01},
        {"type_id": 35, "adjusted_price": None, "average_price": 12.25},
    ]


def run(coro):
    return asyncio.run(coro)


def make_client(handler: Callable[[httpx.Request], httpx.Response], clock: Clock) -> ESIClient:
    async def fake_sleep(seconds: float) -> None:
        return None

    return ESIClient(
        config=Config(user_agent="eve-market-tool/0.1 (contact: test@example.com)"),
        transport=httpx.MockTransport(handler),
        sleep=fake_sleep,
        now=clock,
        backoff_base_seconds=0.01,
    )


def test_ingest_prices_writes_snapshot_and_success_run(tmp_path: Path) -> None:
    clock = Clock()
    snapshot_ts = datetime(2026, 6, 26, 14, 5, 6, tzinfo=timezone.utc)
    config = Config(
        user_agent="eve-market-tool/0.1 (contact: test@example.com)",
        data_dir=tmp_path,
    )
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        return httpx.Response(200, headers=esi_headers(clock), json=prices_payload())

    async def scenario():
        async with make_client(handler, clock) as client:
            return await ingest_prices(client, config, now=snapshot_ts)

    result = run(scenario())

    assert result.status == "success"
    assert result.price_count == 3
    assert result.snapshot_ts == snapshot_ts
    assert result.esi_expires == clock() + timedelta(minutes=5)
    assert requested_paths == ["/latest/markets/prices/"]

    with duckdb.connect(str(tmp_path / "market.duckdb")) as connection:
        connection.execute("SET TimeZone='UTC'")
        price_rows = connection.execute(
            """
            SELECT
                type_id, adjusted_price, average_price, snapshot_ts,
                typeof(type_id), typeof(adjusted_price), typeof(average_price),
                typeof(snapshot_ts)
            FROM market_prices
            ORDER BY type_id
            """
        ).fetchall()
        run_row = connection.execute(
            """
            SELECT
                source, region_id, snapshot_ts, pages, order_count, status,
                esi_expires, snapshot_path, error
            FROM ingest_runs
            WHERE source = 'esi_prices'
            """
        ).fetchone()

    assert price_rows == [
        (18, 33.248, 30.02, snapshot_ts, "BIGINT", "DOUBLE", "DOUBLE", "TIMESTAMP WITH TIME ZONE"),
        (34, 5.01, None, snapshot_ts, "BIGINT", "DOUBLE", "DOUBLE", "TIMESTAMP WITH TIME ZONE"),
        (35, None, 12.25, snapshot_ts, "BIGINT", "DOUBLE", "DOUBLE", "TIMESTAMP WITH TIME ZONE"),
    ]
    assert run_row == (
        "esi_prices",
        None,
        snapshot_ts,
        1,
        3,
        "success",
        clock() + timedelta(minutes=5),
        None,
        None,
    )


def test_ingest_prices_rerun_same_now_is_idempotent(tmp_path: Path) -> None:
    clock = Clock()
    snapshot_ts = datetime(2026, 6, 26, 14, 5, 6, tzinfo=timezone.utc)
    config = Config(
        user_agent="eve-market-tool/0.1 (contact: test@example.com)",
        data_dir=tmp_path,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers=esi_headers(clock), json=prices_payload())

    async def scenario() -> None:
        async with make_client(handler, clock) as client:
            await ingest_prices(client, config, now=snapshot_ts)
            await ingest_prices(client, config, now=snapshot_ts)

    run(scenario())

    with duckdb.connect(str(tmp_path / "market.duckdb")) as connection:
        price_count = connection.execute("SELECT count(*) FROM market_prices").fetchone()[0]
        success_count = connection.execute(
            "SELECT count(*) FROM ingest_runs WHERE source = 'esi_prices'"
        ).fetchone()[0]

    assert price_count == 3
    assert success_count == 2


def test_ingest_prices_records_failed_run(tmp_path: Path) -> None:
    clock = Clock()
    snapshot_ts = datetime(2026, 6, 26, 14, 5, 6, tzinfo=timezone.utc)
    config = Config(
        user_agent="eve-market-tool/0.1 (contact: test@example.com)",
        data_dir=tmp_path,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, headers=esi_headers(clock), json={"error": "bad"})

    async def scenario() -> None:
        async with make_client(handler, clock) as client:
            await ingest_prices(client, config, now=snapshot_ts)

    with pytest.raises(ESIError):
        run(scenario())

    with duckdb.connect(str(tmp_path / "market.duckdb")) as connection:
        row = connection.execute(
            """
            SELECT source, region_id, pages, order_count, status, snapshot_path, error
            FROM ingest_runs
            WHERE source = 'esi_prices'
            """
        ).fetchone()

    assert row[:6] == ("esi_prices", None, 1, 0, "failed", None)
    assert "HTTP 400" in row[6]
