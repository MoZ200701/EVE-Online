"""Writers for market ingestion artifacts."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import polars as pl


ORDER_SCHEMA = {
    "order_id": pl.Int64,
    "type_id": pl.Int64,
    "is_buy_order": pl.Boolean,
    "price": pl.Float64,
    "volume_remain": pl.Int64,
    "volume_total": pl.Int64,
    "min_volume": pl.Int64,
    "location_id": pl.Int64,
    "system_id": pl.Int64,
    "range": pl.Utf8,
    "duration": pl.Int64,
    "issued": pl.Datetime(time_zone="UTC"),
    "region_id": pl.Int64,
    "snapshot_ts": pl.Datetime(time_zone="UTC"),
}

HISTORY_SCHEMA = {
    "date": pl.Date,
    "average": pl.Float64,
    "highest": pl.Float64,
    "lowest": pl.Float64,
    "order_count": pl.Int64,
    "volume": pl.Int64,
    "region_id": pl.Int64,
    "type_id": pl.Int64,
}

PRICE_SCHEMA = {
    "type_id": pl.Int64,
    "adjusted_price": pl.Float64,
    "average_price": pl.Float64,
    "snapshot_ts": pl.Datetime(time_zone="UTC"),
}


def write_orders_snapshot(
    orders: list[dict],
    region_id: int,
    snapshot_ts: datetime,
    snapshots_root: Path,
) -> tuple[Path, int]:
    """Write a partitioned Parquet order-book snapshot."""

    snapshot_ts = _ensure_utc(snapshot_ts)
    rows = [
        {
            **order,
            "issued": _parse_esi_datetime(order["issued"]),
            "region_id": region_id,
            "snapshot_ts": snapshot_ts,
        }
        for order in orders
    ]
    frame = pl.DataFrame(rows, schema=ORDER_SCHEMA, strict=True)

    snapshot_dir = (
        snapshots_root
        / "orders"
        / f"region={region_id}"
        / f"date={snapshot_ts.strftime('%Y-%m-%d')}"
    )
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshot_dir / f"{snapshot_ts.strftime('%Y%m%dT%H%M%SZ')}.parquet"
    frame.write_parquet(snapshot_path, compression="zstd")
    return snapshot_path, frame.height


def write_history(
    conn: duckdb.DuckDBPyConnection,
    region_id: int,
    type_id: int,
    days: list[dict],
) -> int:
    """Upsert daily market history rows for one region/type pair."""

    rows = [
        {
            **day,
            "date": _parse_esi_date(day["date"]),
            "region_id": region_id,
            "type_id": type_id,
        }
        for day in days
    ]
    frame = pl.DataFrame(rows, schema=HISTORY_SCHEMA, strict=True)
    return _upsert_history_frame(conn, frame)


def write_history_bulk(conn: duckdb.DuckDBPyConnection, rows: list[dict]) -> int:
    """Upsert daily market history rows spanning multiple types/dates."""

    if not rows:
        return 0
    frame = pl.DataFrame(rows, schema=HISTORY_SCHEMA, strict=True)
    return _upsert_history_frame(conn, frame)


def write_prices(
    conn: duckdb.DuckDBPyConnection,
    prices: list[dict],
    snapshot_ts: datetime,
) -> int:
    """Upsert one global ESI market-prices snapshot."""

    if not prices:
        return 0

    snapshot_ts = _ensure_utc(snapshot_ts)
    rows = [
        {
            "type_id": price["type_id"],
            "adjusted_price": price.get("adjusted_price"),
            "average_price": price.get("average_price"),
            "snapshot_ts": snapshot_ts,
        }
        for price in prices
    ]
    frame = pl.DataFrame(rows, schema=PRICE_SCHEMA, strict=True)
    conn.execute(
        """
        CREATE TEMP TABLE price_rows (
            type_id BIGINT,
            adjusted_price DOUBLE,
            average_price DOUBLE,
            snapshot_ts TIMESTAMPTZ
        )
        """
    )
    try:
        conn.executemany(
            """
            INSERT INTO price_rows (
                type_id, adjusted_price, average_price, snapshot_ts
            )
            VALUES (?, ?, ?, ?)
            """,
            frame.select(
                [
                    "type_id",
                    "adjusted_price",
                    "average_price",
                    "snapshot_ts",
                ]
            ).rows(),
        )
        conn.execute(
            """
            INSERT INTO market_prices (
                type_id, adjusted_price, average_price, snapshot_ts
            )
            SELECT type_id, adjusted_price, average_price, snapshot_ts
            FROM price_rows
            ON CONFLICT (type_id, snapshot_ts) DO UPDATE SET
                adjusted_price = EXCLUDED.adjusted_price,
                average_price = EXCLUDED.average_price
            """
        )
    finally:
        conn.execute("DROP TABLE IF EXISTS price_rows")
    return frame.height


def _upsert_history_frame(conn: duckdb.DuckDBPyConnection, frame: pl.DataFrame) -> int:
    if frame.is_empty():
        return 0

    conn.execute(
        """
        CREATE TEMP TABLE history_rows (
            date DATE,
            average DOUBLE,
            highest DOUBLE,
            lowest DOUBLE,
            order_count BIGINT,
            volume BIGINT,
            region_id BIGINT,
            type_id BIGINT
        )
        """
    )
    try:
        conn.executemany(
            """
            INSERT INTO history_rows (
                date, average, highest, lowest, order_count, volume, region_id, type_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            frame.select(
                [
                    "date",
                    "average",
                    "highest",
                    "lowest",
                    "order_count",
                    "volume",
                    "region_id",
                    "type_id",
                ]
            ).rows(),
        )
        conn.execute(
            """
            INSERT INTO market_history (
                region_id, type_id, date, average, highest, lowest, order_count, volume
            )
            SELECT
                region_id, type_id, date, average, highest, lowest, order_count, volume
            FROM history_rows
            ON CONFLICT (region_id, type_id, date) DO UPDATE SET
                average = EXCLUDED.average,
                highest = EXCLUDED.highest,
                lowest = EXCLUDED.lowest,
                order_count = EXCLUDED.order_count,
                volume = EXCLUDED.volume
            """
        )
    finally:
        conn.execute("DROP TABLE IF EXISTS history_rows")
    return frame.height


def record_ingest_run(
    conn: duckdb.DuckDBPyConnection,
    **fields: Any,
) -> None:
    """Insert one row into ingest_runs."""

    conn.execute(
        """
        INSERT INTO ingest_runs (
            run_id, source, region_id, snapshot_ts, started_at, finished_at,
            status, order_count, pages, esi_expires, snapshot_path, error
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            fields["run_id"],
            fields["source"],
            fields["region_id"],
            fields["snapshot_ts"],
            fields["started_at"],
            fields["finished_at"],
            fields["status"],
            fields["order_count"],
            fields["pages"],
            fields.get("esi_expires"),
            fields.get("snapshot_path"),
            fields.get("error"),
        ],
    )


def _parse_esi_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return _ensure_utc(value)
    return _ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _parse_esi_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
