from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import duckdb
import httpx
import pytest

from evemarket.config import Config
from evemarket.esi.client import ESIClient, ESIError
from evemarket.ingest.history import ingest_history


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 6, 26, 12, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value


def history_payload(type_id: int) -> list[dict]:
    return [
        {
            "date": "2026-06-24",
            "average": float(type_id) + 0.1,
            "highest": float(type_id) + 0.2,
            "lowest": float(type_id) + 0.3,
            "order_count": type_id + 10,
            "volume": type_id + 100,
        },
        {
            "date": "2026-06-25",
            "average": float(type_id) + 1.1,
            "highest": float(type_id) + 1.2,
            "lowest": float(type_id) + 1.3,
            "order_count": type_id + 20,
            "volume": type_id + 200,
        },
    ]


def esi_headers(clock: Clock) -> dict[str, str]:
    return {
        "Expires": format_datetime(clock() + timedelta(minutes=5)),
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


def test_ingest_history_writes_rows_and_success_run(tmp_path: Path) -> None:
    clock = Clock()
    snapshot_ts = datetime(2026, 6, 26, 14, 5, 6, tzinfo=timezone.utc)
    config = Config(
        user_agent="eve-market-tool/0.1 (contact: test@example.com)",
        data_dir=tmp_path,
    )
    requested_type_ids: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_type_id = int(request.url.params["type_id"])
        requested_type_ids.append(requested_type_id)
        return httpx.Response(
            200,
            headers=esi_headers(clock),
            json=history_payload(requested_type_id),
        )

    async def scenario():
        async with make_client(handler, clock) as client:
            return await ingest_history(
                client,
                config,
                10000002,
                [34, 35],
                now=snapshot_ts,
            )

    result = run(scenario())

    assert result.status == "success"
    assert result.region_id == 10000002
    assert result.type_ids == [34, 35]
    assert result.types_fetched == 2
    assert result.day_count == 4
    assert requested_type_ids == [34, 35]

    with duckdb.connect(str(tmp_path / "market.duckdb")) as connection:
        connection.execute("SET TimeZone='UTC'")
        history_rows = connection.execute(
            """
            SELECT
                region_id, type_id, date, average, highest, lowest, order_count, volume
            FROM market_history
            ORDER BY type_id, date
            """
        ).fetchall()
        run_row = connection.execute(
            """
            SELECT
                source, region_id, snapshot_ts, pages, order_count, status,
                esi_expires, snapshot_path, error
            FROM ingest_runs
            """
        ).fetchone()

    assert history_rows == [
        (10000002, 34, date(2026, 6, 24), 34.1, 34.2, 34.3, 44, 134),
        (10000002, 34, date(2026, 6, 25), 35.1, 35.2, 35.3, 54, 234),
        (10000002, 35, date(2026, 6, 24), 35.1, 35.2, 35.3, 45, 135),
        (10000002, 35, date(2026, 6, 25), 36.1, 36.2, 36.3, 55, 235),
    ]
    assert run_row == (
        "esi_history",
        10000002,
        snapshot_ts,
        2,
        4,
        "success",
        clock() + timedelta(minutes=5),
        None,
        None,
    )


def test_ingest_history_rerun_is_idempotent(tmp_path: Path) -> None:
    clock = Clock()
    snapshot_ts = datetime(2026, 6, 26, 14, 5, 6, tzinfo=timezone.utc)
    config = Config(
        user_agent="eve-market-tool/0.1 (contact: test@example.com)",
        data_dir=tmp_path,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers=esi_headers(clock),
            json=history_payload(int(request.url.params["type_id"])),
        )

    async def scenario() -> None:
        async with make_client(handler, clock) as client:
            await ingest_history(client, config, 10000002, [34], now=snapshot_ts)
            await ingest_history(client, config, 10000002, [34], now=snapshot_ts)

    run(scenario())

    with duckdb.connect(str(tmp_path / "market.duckdb")) as connection:
        history_count = connection.execute("SELECT count(*) FROM market_history").fetchone()[0]
        success_count = connection.execute(
            "SELECT count(*) FROM ingest_runs WHERE source = 'esi_history'"
        ).fetchone()[0]

    assert history_count == 2
    assert success_count == 2


def test_ingest_history_records_failed_run(tmp_path: Path) -> None:
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
            await ingest_history(client, config, 10000002, [34], now=snapshot_ts)

    with pytest.raises(ESIError):
        run(scenario())

    with duckdb.connect(str(tmp_path / "market.duckdb")) as connection:
        row = connection.execute(
            """
            SELECT source, region_id, pages, order_count, status, snapshot_path, error
            FROM ingest_runs
            """
        ).fetchone()

    assert row[:6] == ("esi_history", 10000002, 1, 0, "failed", None)
    assert "HTTP 400" in row[6]
