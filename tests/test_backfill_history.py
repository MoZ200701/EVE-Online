from __future__ import annotations

import bz2
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pytest

from evemarket.config import Config
from evemarket.ingest.backfill import backfill_history_everef


def csv_bz2(day: date) -> bytes:
    csv = "\n".join(
        [
            "average,date,highest,lowest,order_count,volume,http_last_modified,region_id,type_id",
            f"6.10,{day:%Y-%m-%d},6.50,5.90,11,1000,2026-06-26T11:01:54Z,10000002,34",
            f"12.25,{day:%Y-%m-%d},13.00,12.00,22,2000,2026-06-26T11:01:54Z,10000002,35",
            f"99.99,{day:%Y-%m-%d},100.00,90.00,33,3000,2026-06-26T11:01:54Z,10000001,34",
        ]
    )
    return bz2.compress(csv.encode("utf-8"))


def config(tmp_path: Path) -> Config:
    return Config(
        user_agent="eve-market-tool/0.1 (contact: test@example.com)",
        data_dir=tmp_path,
    )


def test_backfill_history_filters_region_records_success_and_skips_missing(
    tmp_path: Path,
) -> None:
    start = date(2026, 6, 24)
    end = date(2026, 6, 26)
    now = datetime(2026, 6, 27, 12, tzinfo=timezone.utc)
    payloads = {
        "market-history-2026-06-24.csv.bz2": csv_bz2(date(2026, 6, 24)),
        "market-history-2026-06-25.csv.bz2": csv_bz2(date(2026, 6, 25)),
    }
    requested_urls: list[str] = []

    def fetch(url: str) -> bytes | None:
        requested_urls.append(url)
        return next((payload for key, payload in payloads.items() if key in url), None)

    result = backfill_history_everef(
        config(tmp_path),
        10000002,
        start,
        end,
        fetch=fetch,
        sleep=lambda seconds: None,
        now=now,
    )

    assert result.status == "success"
    assert result.region_id == 10000002
    assert result.start_date == start
    assert result.end_date == end
    assert result.days_fetched == 2
    assert result.days_missing == 1
    assert result.row_count == 4
    assert len(requested_urls) == 3

    with duckdb.connect(str(tmp_path / "market.duckdb")) as connection:
        connection.execute("SET TimeZone='UTC'")
        history_rows = connection.execute(
            """
            SELECT
                region_id, type_id, date, average, highest, lowest, order_count, volume,
                typeof(date), typeof(average), typeof(order_count)
            FROM market_history
            ORDER BY date, type_id
            """
        ).fetchall()
        run_row = connection.execute(
            """
            SELECT
                source, region_id, snapshot_ts, pages, order_count, status,
                esi_expires, snapshot_path, error
            FROM ingest_runs
            WHERE source = 'everef_history'
            """
        ).fetchone()

    assert history_rows == [
        (10000002, 34, date(2026, 6, 24), 6.10, 6.50, 5.90, 11, 1000, "DATE", "DOUBLE", "BIGINT"),
        (10000002, 35, date(2026, 6, 24), 12.25, 13.00, 12.00, 22, 2000, "DATE", "DOUBLE", "BIGINT"),
        (10000002, 34, date(2026, 6, 25), 6.10, 6.50, 5.90, 11, 1000, "DATE", "DOUBLE", "BIGINT"),
        (10000002, 35, date(2026, 6, 25), 12.25, 13.00, 12.00, 22, 2000, "DATE", "DOUBLE", "BIGINT"),
    ]
    assert run_row == (
        "everef_history",
        10000002,
        now,
        2,
        4,
        "success",
        None,
        None,
        None,
    )


def test_backfill_history_rerun_is_idempotent(tmp_path: Path) -> None:
    start = date(2026, 6, 24)
    end = date(2026, 6, 25)
    now = datetime(2026, 6, 27, 12, tzinfo=timezone.utc)

    def fetch(url: str) -> bytes | None:
        return csv_bz2(date.fromisoformat(url.removesuffix(".csv.bz2")[-10:]))

    loaded_config = config(tmp_path)
    for _ in range(2):
        backfill_history_everef(
            loaded_config,
            10000002,
            start,
            end,
            fetch=fetch,
            sleep=lambda seconds: None,
            now=now,
        )

    with duckdb.connect(str(tmp_path / "market.duckdb")) as connection:
        history_count = connection.execute("SELECT count(*) FROM market_history").fetchone()[0]
        success_count = connection.execute(
            "SELECT count(*) FROM ingest_runs WHERE source = 'everef_history'"
        ).fetchone()[0]

    assert history_count == 4
    assert success_count == 2


def test_backfill_history_records_failed_run(tmp_path: Path) -> None:
    start = date(2026, 6, 24)
    now = datetime(2026, 6, 27, 12, tzinfo=timezone.utc)

    def fetch(url: str) -> bytes | None:
        raise RuntimeError("HTTP 500")

    with pytest.raises(RuntimeError, match="HTTP 500"):
        backfill_history_everef(
            config(tmp_path),
            10000002,
            start,
            start,
            fetch=fetch,
            sleep=lambda seconds: None,
            now=now,
        )

    with duckdb.connect(str(tmp_path / "market.duckdb")) as connection:
        row = connection.execute(
            """
            SELECT source, region_id, pages, order_count, status, snapshot_path, error
            FROM ingest_runs
            WHERE source = 'everef_history'
            """
        ).fetchone()

    assert row[:6] == ("everef_history", 10000002, 0, 0, "failed", None)
    assert "HTTP 500" in row[6]
