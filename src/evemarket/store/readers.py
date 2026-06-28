"""Readers for market analytics inputs."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import duckdb

from evemarket.analytics.haul import HaulQuote
from evemarket.analytics.station_trade import MarketQuote
from evemarket.config import Config
from evemarket.store.schema import (
    INGEST_RUNS_TABLE,
    MARKET_HISTORY_TABLE,
    ensure_market_db,
)

SDE_TYPES_TABLE = "sde_types"
SDE_TYPES_ALIAS = "sde_ref"


def read_station_quotes(
    config: Config,
    region_id: int,
    station_id: int,
    *,
    volume_window_days: int = 30,
) -> list[MarketQuote]:
    """Read latest station market quotes for one region/station."""
    if volume_window_days < 1:
        raise ValueError("volume_window_days must be at least 1")

    data_dir = config.data_dir.expanduser()
    market_path = data_dir / "market.duckdb"
    sde_path = data_dir / "sde.duckdb"

    with ensure_market_db(market_path) as connection:
        snapshot_path = _latest_snapshot_path(connection, region_id)
        if snapshot_path is None:
            return []

        quote_rows = _read_best_quotes(connection, snapshot_path, station_id)
        if not quote_rows:
            return []

        type_ids = [type_id for type_id, _, _ in quote_rows]
        volumes = _read_daily_volumes(
            connection,
            region_id,
            volume_window_days=volume_window_days,
        )
        names = _read_type_names(connection, sde_path, type_ids)

    return [
        MarketQuote(
            type_id=type_id,
            type_name=names.get(type_id, f"#{type_id}"),
            best_bid=best_bid,
            best_ask=best_ask,
            daily_volume=volumes.get(type_id, 0.0),
        )
        for type_id, best_bid, best_ask in quote_rows
    ]


def read_haul_quotes(
    config: Config,
    source_region_id: int,
    source_station_id: int,
    dest_region_id: int,
    dest_station_id: int,
    *,
    volume_window_days: int = 30,
) -> list[HaulQuote]:
    """Read latest executable haul quotes for source and destination hubs."""
    if volume_window_days < 1:
        raise ValueError("volume_window_days must be at least 1")

    data_dir = config.data_dir.expanduser()
    market_path = data_dir / "market.duckdb"
    sde_path = data_dir / "sde.duckdb"

    with ensure_market_db(market_path) as connection:
        source_snapshot = _latest_snapshot_path(connection, source_region_id)
        dest_snapshot = _latest_snapshot_path(connection, dest_region_id)
        if source_snapshot is None or dest_snapshot is None:
            return []

        source_asks = {
            type_id: best_ask
            for type_id, _, best_ask in _read_best_quotes(
                connection,
                source_snapshot,
                source_station_id,
            )
            if best_ask > 0
        }
        dest_bids = {
            type_id: best_bid
            for type_id, best_bid, _ in _read_best_quotes(
                connection,
                dest_snapshot,
                dest_station_id,
            )
            if best_bid > 0
        }
        type_ids = sorted(source_asks.keys() & dest_bids.keys())
        if not type_ids:
            return []

        volumes = _read_daily_volumes(
            connection,
            dest_region_id,
            volume_window_days=volume_window_days,
        )
        metadata = _read_type_metadata(connection, sde_path, type_ids)

    return [
        HaulQuote(
            type_id=type_id,
            type_name=metadata.get(type_id, (f"#{type_id}", 0.0))[0],
            source_price=source_asks[type_id],
            dest_price=dest_bids[type_id],
            volume_m3=metadata.get(type_id, (f"#{type_id}", 0.0))[1],
            daily_volume=volumes.get(type_id, 0.0),
        )
        for type_id in type_ids
    ]


def _latest_snapshot_path(
    connection: duckdb.DuckDBPyConnection,
    region_id: int,
) -> Path | None:
    row = connection.execute(
        f"""
        SELECT snapshot_path
        FROM {INGEST_RUNS_TABLE}
        WHERE source = 'esi_orders'
          AND status = 'success'
          AND region_id = ?
          AND snapshot_path IS NOT NULL
        ORDER BY snapshot_ts DESC
        LIMIT 1
        """,
        [region_id],
    ).fetchone()
    if row is None:
        return None
    return Path(str(row[0]))


def _read_best_quotes(
    connection: duckdb.DuckDBPyConnection,
    snapshot_path: Path,
    station_id: int,
) -> list[tuple[int, float, float]]:
    rows = connection.execute(
        """
        SELECT
            type_id,
            COALESCE(MAX(price) FILTER (WHERE is_buy_order), 0.0) AS best_bid,
            COALESCE(MIN(price) FILTER (WHERE NOT is_buy_order), 0.0) AS best_ask
        FROM read_parquet(?)
        WHERE location_id = ?
        GROUP BY type_id
        ORDER BY type_id
        """,
        [str(snapshot_path), station_id],
    ).fetchall()
    return [(int(type_id), float(best_bid), float(best_ask)) for type_id, best_bid, best_ask in rows]


def _read_daily_volumes(
    connection: duckdb.DuckDBPyConnection,
    region_id: int,
    *,
    volume_window_days: int,
) -> dict[int, float]:
    ref_row = connection.execute(
        f"SELECT MAX(date) FROM {MARKET_HISTORY_TABLE} WHERE region_id = ?",
        [region_id],
    ).fetchone()
    if ref_row is None or ref_row[0] is None:
        return {}

    window_start = ref_row[0] - timedelta(days=volume_window_days - 1)
    rows = connection.execute(
        f"""
        SELECT type_id, AVG(volume) AS daily_volume
        FROM {MARKET_HISTORY_TABLE}
        WHERE region_id = ?
          AND date >= ?
        GROUP BY type_id
        """,
        [region_id, window_start],
    ).fetchall()
    return {int(type_id): float(daily_volume) for type_id, daily_volume in rows}


def _read_type_names(
    connection: duckdb.DuckDBPyConnection,
    sde_path: Path,
    type_ids: list[int],
) -> dict[int, str]:
    if not type_ids or not sde_path.exists():
        return {}

    connection.execute(
        f"ATTACH {_duckdb_string_literal(sde_path)} AS {SDE_TYPES_ALIAS} (READ_ONLY)"
    )
    try:
        rows = connection.execute(
            f"""
            SELECT type_id, type_name
            FROM {SDE_TYPES_ALIAS}.{SDE_TYPES_TABLE}
            WHERE type_id IN (SELECT UNNEST(?))
            """,
            [type_ids],
        ).fetchall()
    finally:
        connection.execute(f"DETACH {SDE_TYPES_ALIAS}")

    return {int(type_id): str(type_name) for type_id, type_name in rows}


def _read_type_metadata(
    connection: duckdb.DuckDBPyConnection,
    sde_path: Path,
    type_ids: list[int],
) -> dict[int, tuple[str, float]]:
    if not type_ids or not sde_path.exists():
        return {}

    connection.execute(
        f"ATTACH {_duckdb_string_literal(sde_path)} AS {SDE_TYPES_ALIAS} (READ_ONLY)"
    )
    try:
        rows = connection.execute(
            f"""
            SELECT type_id, type_name, volume
            FROM {SDE_TYPES_ALIAS}.{SDE_TYPES_TABLE}
            WHERE type_id IN (SELECT UNNEST(?))
            """,
            [type_ids],
        ).fetchall()
    finally:
        connection.execute(f"DETACH {SDE_TYPES_ALIAS}")

    return {
        int(type_id): (str(type_name), float(volume))
        for type_id, type_name, volume in rows
    }


def _duckdb_string_literal(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"
