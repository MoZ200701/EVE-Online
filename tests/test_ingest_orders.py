from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import duckdb
import httpx
import polars as pl
import pytest

from evemarket.config import Config
from evemarket.esi.client import ESIClient, ESIError
from evemarket.ingest.orders import ingest_orders


def order_payload(order_id: int, *, system_id: int | None = 30000142) -> dict:
    return {
        "order_id": order_id,
        "type_id": 34,
        "is_buy_order": False,
        "price": 6.25,
        "volume_remain": 100,
        "volume_total": 200,
        "min_volume": 1,
        "location_id": 60003760,
        "system_id": system_id,
        "range": "region",
        "duration": 90,
        "issued": "2026-06-25T12:00:00Z",
    }


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 6, 26, 12, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value


def esi_headers(clock: Clock, *, pages: int = 1) -> dict[str, str]:
    return {
        "Expires": format_datetime(clock() + timedelta(minutes=5)),
        "X-Pages": str(pages),
        "X-ESI-Error-Limit-Remain": "100",
        "X-ESI-Error-Limit-Reset": "1",
    }


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


def test_ingest_orders_writes_snapshot_and_success_run(tmp_path: Path) -> None:
    clock = Clock()
    requested_pages: list[int] = []
    snapshot_ts = datetime(2026, 6, 26, 14, 5, 6, tzinfo=timezone.utc)
    config = Config(
        user_agent="eve-market-tool/0.1 (contact: test@example.com)",
        data_dir=tmp_path,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        requested_pages.append(page)
        headers = esi_headers(clock, pages=2)
        payload = (
            [order_payload(1)]
            if page == 1
            else [order_payload(2, system_id=None), order_payload(3)]
        )
        return httpx.Response(200, headers=headers, json=payload)

    async def scenario():
        async with make_client(handler, clock) as client:
            return await ingest_orders(client, config, 10000002, now=snapshot_ts)

    result = run(scenario())

    expected_path = (
        tmp_path
        / "snapshots"
        / "orders"
        / "region=10000002"
        / "date=2026-06-26"
        / "20260626T140506Z.parquet"
    )
    assert result.status == "success"
    assert result.pages == 2
    assert result.order_count == 3
    assert result.snapshot_path == expected_path
    assert expected_path.exists()
    assert sorted(requested_pages) == [1, 2]
    expected_esi_expires = clock() + timedelta(minutes=5)

    frame = pl.read_parquet(expected_path)
    assert frame.columns == [
        "order_id",
        "type_id",
        "is_buy_order",
        "price",
        "volume_remain",
        "volume_total",
        "min_volume",
        "location_id",
        "system_id",
        "range",
        "duration",
        "issued",
        "region_id",
        "snapshot_ts",
    ]
    assert frame.schema["issued"] == pl.Datetime(time_zone="UTC")
    assert frame.schema["snapshot_ts"] == pl.Datetime(time_zone="UTC")
    assert frame["region_id"].to_list() == [10000002, 10000002, 10000002]
    assert frame["snapshot_ts"].to_list() == [snapshot_ts, snapshot_ts, snapshot_ts]

    with duckdb.connect(str(tmp_path / "market.duckdb")) as connection:
        connection.execute("SET TimeZone='UTC'")
        row = connection.execute(
            """
            SELECT
                source, region_id, snapshot_ts, started_at, finished_at, pages,
                order_count, status, esi_expires, snapshot_path, error
            FROM ingest_runs
            """
        ).fetchone()

    (
        source,
        region_id,
        stored_snapshot_ts,
        started_at,
        finished_at,
        pages,
        order_count,
        status,
        esi_expires,
        snapshot_path,
        error,
    ) = row
    assert (source, region_id, pages, order_count, status, snapshot_path, error) == (
        "esi_orders",
        10000002,
        2,
        3,
        "success",
        str(expected_path),
        None,
    )
    assert stored_snapshot_ts == snapshot_ts
    assert esi_expires == expected_esi_expires
    assert started_at.tzinfo is not None
    assert finished_at.tzinfo is not None
    assert started_at.utcoffset() == timedelta(0)
    assert finished_at.utcoffset() == timedelta(0)


def test_ingest_orders_records_failed_run_without_parquet(tmp_path: Path) -> None:
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
            await ingest_orders(client, config, 10000002, now=snapshot_ts)

    with pytest.raises(ESIError):
        run(scenario())

    assert not (tmp_path / "snapshots").exists()
    with duckdb.connect(str(tmp_path / "market.duckdb")) as connection:
        row = connection.execute(
            """
            SELECT source, region_id, pages, order_count, status, snapshot_path, error
            FROM ingest_runs
            """
        ).fetchone()

    assert row[:6] == ("esi_orders", 10000002, 0, 0, "failed", None)
    assert "HTTP 400" in row[6]
