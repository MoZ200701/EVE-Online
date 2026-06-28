from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pytest

from evemarket.analytics.station_trade import scan_station_trades
from evemarket.config import Config
from evemarket.store.readers import read_station_quotes
from evemarket.store.schema import ensure_market_db
from evemarket.store.writers import record_ingest_run, write_orders_snapshot

REGION_ID = 10000002
STATION_ID = 60003760
OTHER_STATION_ID = 60003761


def test_read_station_quotes_from_latest_snapshot(tmp_path: Path) -> None:
    snapshot_path = _write_snapshot(
        tmp_path,
        datetime(2026, 6, 28, 12, tzinfo=timezone.utc),
        [
            _order(1, 34, True, 100, STATION_ID),
            _order(2, 34, False, 120, STATION_ID),
            _order(3, 35, False, 200, STATION_ID),
            _order(4, 34, True, 500, OTHER_STATION_ID),
        ],
    )
    _write_market_db(tmp_path, snapshot_path)
    _write_sde_db(tmp_path)

    quotes = read_station_quotes(Config(data_dir=tmp_path), REGION_ID, STATION_ID)

    assert quotes[0].type_id == 34
    assert quotes[0].type_name == "Tritanium"
    assert quotes[0].best_bid == pytest.approx(100)
    assert quotes[0].best_ask == pytest.approx(120)
    assert quotes[0].daily_volume == pytest.approx(1500)
    assert quotes[1].type_id == 35
    assert quotes[1].type_name == "#35"
    assert quotes[1].best_bid == pytest.approx(0.0)
    assert quotes[1].best_ask == pytest.approx(200)
    assert quotes[1].daily_volume == pytest.approx(0.0)


def test_read_station_quotes_uses_latest_snapshot(tmp_path: Path) -> None:
    older_snapshot = _write_snapshot(
        tmp_path,
        datetime(2026, 6, 27, 12, tzinfo=timezone.utc),
        [
            _order(1, 34, True, 80, STATION_ID),
            _order(2, 34, False, 110, STATION_ID),
        ],
    )
    newer_snapshot = _write_snapshot(
        tmp_path,
        datetime(2026, 6, 28, 12, tzinfo=timezone.utc),
        [
            _order(3, 34, True, 100, STATION_ID),
            _order(4, 34, False, 120, STATION_ID),
        ],
    )
    _write_market_db(tmp_path, older_snapshot, newer_snapshot)

    quotes = read_station_quotes(Config(data_dir=tmp_path), REGION_ID, STATION_ID)

    assert [(quote.best_bid, quote.best_ask) for quote in quotes] == [
        (pytest.approx(100), pytest.approx(120))
    ]


def test_read_station_quotes_returns_empty_without_snapshot(tmp_path: Path) -> None:
    with ensure_market_db(tmp_path / "market.duckdb"):
        pass

    assert read_station_quotes(Config(data_dir=tmp_path), REGION_ID, STATION_ID) == []


def test_read_station_quotes_feeds_station_trade_scanner(tmp_path: Path) -> None:
    snapshot_path = _write_snapshot(
        tmp_path,
        datetime(2026, 6, 28, 12, tzinfo=timezone.utc),
        [
            _order(1, 34, True, 100, STATION_ID),
            _order(2, 34, False, 120, STATION_ID),
            _order(3, 35, False, 200, STATION_ID),
        ],
    )
    _write_market_db(tmp_path, snapshot_path)

    quotes = read_station_quotes(Config(data_dir=tmp_path), REGION_ID, STATION_ID)
    results = scan_station_trades(quotes, Config())

    assert [result.type_id for result in results] == [34]


def test_read_station_quotes_rejects_bad_volume_window(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        read_station_quotes(Config(data_dir=tmp_path), REGION_ID, STATION_ID, volume_window_days=0)


def _write_snapshot(
    data_dir: Path,
    snapshot_ts: datetime,
    orders: list[dict[str, object]],
) -> Path:
    snapshot_path, _ = write_orders_snapshot(
        orders,
        REGION_ID,
        snapshot_ts,
        data_dir / "snapshots",
    )
    return snapshot_path


def _write_market_db(data_dir: Path, *snapshot_paths: Path) -> None:
    with ensure_market_db(data_dir / "market.duckdb") as connection:
        for index, snapshot_path in enumerate(snapshot_paths):
            snapshot_ts = datetime(2026, 6, 27 + index, 12, tzinfo=timezone.utc)
            record_ingest_run(
                connection,
                run_id=f"run-{index}",
                source="esi_orders",
                region_id=REGION_ID,
                snapshot_ts=snapshot_ts,
                started_at=snapshot_ts,
                finished_at=snapshot_ts,
                status="success",
                order_count=2,
                pages=1,
                snapshot_path=str(snapshot_path),
            )
        connection.executemany(
            """
            INSERT INTO market_history (
                region_id, type_id, date, average, highest, lowest, order_count, volume
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (REGION_ID, 34, date(2026, 6, 27), 100.0, 120.0, 90.0, 10, 1000),
                (REGION_ID, 34, date(2026, 6, 28), 100.0, 120.0, 90.0, 10, 2000),
            ],
        )


def _write_sde_db(data_dir: Path) -> None:
    with duckdb.connect(str(data_dir / "sde.duckdb")) as connection:
        connection.execute(
            """
            CREATE TABLE sde_types (
                type_id BIGINT PRIMARY KEY,
                type_name TEXT
            )
            """
        )
        connection.execute("INSERT INTO sde_types VALUES (?, ?)", [34, "Tritanium"])


def _order(
    order_id: int,
    type_id: int,
    is_buy_order: bool,
    price: float,
    location_id: int,
) -> dict[str, object]:
    return {
        "order_id": order_id,
        "type_id": type_id,
        "is_buy_order": is_buy_order,
        "price": price,
        "volume_remain": 100,
        "volume_total": 100,
        "min_volume": 1,
        "location_id": location_id,
        "system_id": 30000142,
        "range": "station",
        "duration": 90,
        "issued": datetime(2026, 6, 28, tzinfo=timezone.utc),
    }
