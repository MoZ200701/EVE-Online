"""DuckDB schema helpers for market ingestion."""

from __future__ import annotations

from pathlib import Path

import duckdb

INGEST_RUNS_TABLE = "ingest_runs"
MARKET_HISTORY_TABLE = "market_history"
MARKET_PRICES_TABLE = "market_prices"


def ensure_market_db(path: str | Path) -> duckdb.DuckDBPyConnection:
    """Open the market DuckDB file and ensure bookkeeping tables exist."""

    duckdb_path = Path(path)
    duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(duckdb_path))
    connection.execute("SET TimeZone='UTC'")
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {INGEST_RUNS_TABLE} (
            run_id TEXT,
            source TEXT,
            region_id BIGINT,
            snapshot_ts TIMESTAMPTZ,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            status TEXT,
            order_count BIGINT,
            pages INTEGER,
            esi_expires TIMESTAMPTZ,
            snapshot_path TEXT,
            error TEXT
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MARKET_HISTORY_TABLE} (
            region_id BIGINT,
            type_id BIGINT,
            date DATE,
            average DOUBLE,
            highest DOUBLE,
            lowest DOUBLE,
            order_count BIGINT,
            volume BIGINT,
            PRIMARY KEY (region_id, type_id, date)
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MARKET_PRICES_TABLE} (
            type_id BIGINT,
            adjusted_price DOUBLE,
            average_price DOUBLE,
            snapshot_ts TIMESTAMPTZ,
            PRIMARY KEY (type_id, snapshot_ts)
        )
        """
    )
    return connection
