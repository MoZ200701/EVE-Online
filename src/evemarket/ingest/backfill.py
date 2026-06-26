"""Historical market-history backfill from everef.net."""

from __future__ import annotations

import bz2
import io
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import httpx
import polars as pl

from evemarket.config import Config
from evemarket.store.schema import ensure_market_db
from evemarket.store.writers import HISTORY_SCHEMA, record_ingest_run, write_history_bulk

EVEREF_BASE_URL = "https://data.everef.net/market-history"
EVEREF_CSV_SCHEMA = {
    "average": pl.Float64,
    "date": pl.Utf8,
    "highest": pl.Float64,
    "lowest": pl.Float64,
    "order_count": pl.Int64,
    "volume": pl.Int64,
    "http_last_modified": pl.Utf8,
    "region_id": pl.Int64,
    "type_id": pl.Int64,
}
HISTORY_COLUMNS = list(HISTORY_SCHEMA)
POLITENESS_DELAY_SECONDS = 0.5

FetchCallable = Callable[[str], bytes | None]
SleepCallable = Callable[[float], None]


@dataclass(frozen=True)
class BackfillResult:
    run_id: str
    region_id: int
    start_date: date
    end_date: date
    days_fetched: int
    days_missing: int
    row_count: int
    status: str


def backfill_history_everef(
    config: Config,
    region_id: int,
    start_date: date,
    end_date: date,
    *,
    fetch: FetchCallable | None = None,
    sleep: SleepCallable | None = None,
    now: datetime | None = None,
) -> BackfillResult:
    """Backfill daily market history from everef.net static CSV dumps."""

    snapshot_ts = _ensure_utc(now or datetime.now(timezone.utc))
    started_at = snapshot_ts
    run_id = str(uuid4())
    market_db_path = config.data_dir.expanduser() / "market.duckdb"
    sleep_func = sleep or time.sleep
    days_fetched = 0
    days_missing = 0
    all_rows: list[dict] = []
    dates = list(_date_range(start_date, end_date))

    try:
        if fetch is None:
            with httpx.Client(headers={"User-Agent": config.user_agent}) as client:
                for current_date in dates:
                    raw = _default_fetch(client, _everef_url(current_date))
                    rows = _rows_from_raw(raw, region_id)
                    if rows is None:
                        days_missing += 1
                    elif rows:
                        all_rows.extend(rows)
                        days_fetched += 1
                    sleep_func(POLITENESS_DELAY_SECONDS)
        else:
            for current_date in dates:
                raw = fetch(_everef_url(current_date))
                rows = _rows_from_raw(raw, region_id)
                if rows is None:
                    days_missing += 1
                elif rows:
                    all_rows.extend(rows)
                    days_fetched += 1
                sleep_func(POLITENESS_DELAY_SECONDS)

        with ensure_market_db(market_db_path) as connection:
            row_count = write_history_bulk(connection, all_rows)
            record_ingest_run(
                connection,
                run_id=run_id,
                source="everef_history",
                region_id=region_id,
                snapshot_ts=snapshot_ts,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                status="success",
                order_count=row_count,
                pages=days_fetched,
                esi_expires=None,
                snapshot_path=None,
                error=None,
            )

        return BackfillResult(
            run_id=run_id,
            region_id=region_id,
            start_date=start_date,
            end_date=end_date,
            days_fetched=days_fetched,
            days_missing=days_missing,
            row_count=row_count,
            status="success",
        )
    except Exception as exc:
        with ensure_market_db(market_db_path) as connection:
            record_ingest_run(
                connection,
                run_id=run_id,
                source="everef_history",
                region_id=region_id,
                snapshot_ts=snapshot_ts,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                status="failed",
                order_count=0,
                pages=days_fetched,
                esi_expires=None,
                snapshot_path=None,
                error=str(exc),
            )
        raise


def _default_fetch(client: httpx.Client, url: str) -> bytes | None:
    response = client.get(url)
    if response.status_code == httpx.codes.NOT_FOUND:
        return None
    response.raise_for_status()
    return response.content


def _rows_from_raw(raw: bytes | None, region_id: int) -> list[dict] | None:
    if raw is None:
        return None
    data = bz2.decompress(raw)
    frame = (
        pl.read_csv(io.BytesIO(data), schema_overrides=EVEREF_CSV_SCHEMA)
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .filter(pl.col("region_id") == region_id)
        .select(HISTORY_COLUMNS)
    )
    return frame.to_dicts()


def _everef_url(day: date) -> str:
    return f"{EVEREF_BASE_URL}/{day:%Y}/market-history-{day:%Y-%m-%d}.csv.bz2"


def _date_range(start_date: date, end_date: date):
    current_date = start_date
    while current_date <= end_date:
        yield current_date
        current_date += timedelta(days=1)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
