"""DuckDB schema helpers for market ingestion."""

from __future__ import annotations

from pathlib import Path

import duckdb

INGEST_RUNS_TABLE = "ingest_runs"


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
    return connection
