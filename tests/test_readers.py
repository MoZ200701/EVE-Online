from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pytest

from evemarket.analytics.features import HistoryBar, compute_features
from evemarket.analytics.backtest import PricePoint, naive_persistence_forecast
from evemarket.analytics.haul import scan_haul_opportunities
from evemarket.analytics.station_trade import scan_station_trades
from evemarket.analytics.walkforward import run_forecaster_backtest
from evemarket.config import Config
from evemarket.store.readers import (
    read_haul_quotes,
    read_history_bars,
    read_price_series,
    read_station_quotes,
)
from evemarket.store.schema import ensure_market_db
from evemarket.store.writers import record_ingest_run, write_orders_snapshot

REGION_ID = 10000002
DEST_REGION_ID = 10000043
STATION_ID = 60003760
DEST_STATION_ID = 60008494
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


def test_read_haul_quotes_executable_pairs(tmp_path: Path) -> None:
    source_snapshot = _write_snapshot(
        tmp_path,
        datetime(2026, 6, 28, 12, tzinfo=timezone.utc),
        [
            _order(1, 34, False, 100, STATION_ID),
            _order(2, 35, False, 100, STATION_ID),
        ],
        region_id=REGION_ID,
    )
    dest_snapshot = _write_snapshot(
        tmp_path,
        datetime(2026, 6, 28, 12, tzinfo=timezone.utc),
        [
            _order(3, 34, True, 130, DEST_STATION_ID),
            _order(4, 36, True, 200, DEST_STATION_ID),
        ],
        region_id=DEST_REGION_ID,
    )
    _write_market_db(
        tmp_path,
        source_snapshot,
        dest_snapshot,
        snapshot_regions=[REGION_ID, DEST_REGION_ID],
    )
    _write_history(tmp_path, DEST_REGION_ID)
    _write_sde_db(tmp_path)

    quotes = read_haul_quotes(
        Config(data_dir=tmp_path),
        REGION_ID,
        STATION_ID,
        DEST_REGION_ID,
        DEST_STATION_ID,
    )

    assert len(quotes) == 1
    assert quotes[0].type_id == 34
    assert quotes[0].type_name == "Tritanium"
    assert quotes[0].source_price == pytest.approx(100)
    assert quotes[0].dest_price == pytest.approx(130)
    assert quotes[0].volume_m3 == pytest.approx(0.01)
    assert quotes[0].daily_volume == pytest.approx(1500)


def test_read_haul_quotes_returns_empty_without_source_snapshot(tmp_path: Path) -> None:
    dest_snapshot = _write_snapshot(
        tmp_path,
        datetime(2026, 6, 28, 12, tzinfo=timezone.utc),
        [_order(1, 34, True, 130, DEST_STATION_ID)],
        region_id=DEST_REGION_ID,
    )
    _write_market_db(tmp_path, dest_snapshot, snapshot_regions=[DEST_REGION_ID])

    assert (
        read_haul_quotes(
            Config(data_dir=tmp_path),
            REGION_ID,
            STATION_ID,
            DEST_REGION_ID,
            DEST_STATION_ID,
        )
        == []
    )


def test_read_haul_quotes_returns_empty_without_dest_snapshot(tmp_path: Path) -> None:
    source_snapshot = _write_snapshot(
        tmp_path,
        datetime(2026, 6, 28, 12, tzinfo=timezone.utc),
        [_order(1, 34, False, 100, STATION_ID)],
        region_id=REGION_ID,
    )
    _write_market_db(tmp_path, source_snapshot)

    assert (
        read_haul_quotes(
            Config(data_dir=tmp_path),
            REGION_ID,
            STATION_ID,
            DEST_REGION_ID,
            DEST_STATION_ID,
        )
        == []
    )


def test_read_haul_quotes_sde_fallback(tmp_path: Path) -> None:
    source_snapshot = _write_snapshot(
        tmp_path,
        datetime(2026, 6, 28, 12, tzinfo=timezone.utc),
        [_order(1, 37, False, 100, STATION_ID)],
        region_id=REGION_ID,
    )
    dest_snapshot = _write_snapshot(
        tmp_path,
        datetime(2026, 6, 28, 12, tzinfo=timezone.utc),
        [_order(2, 37, True, 130, DEST_STATION_ID)],
        region_id=DEST_REGION_ID,
    )
    _write_market_db(
        tmp_path,
        source_snapshot,
        dest_snapshot,
        snapshot_regions=[REGION_ID, DEST_REGION_ID],
    )

    quotes = read_haul_quotes(
        Config(data_dir=tmp_path),
        REGION_ID,
        STATION_ID,
        DEST_REGION_ID,
        DEST_STATION_ID,
    )

    assert quotes[0].type_id == 37
    assert quotes[0].type_name == "#37"
    assert quotes[0].volume_m3 == pytest.approx(0.0)


def test_read_haul_quotes_feeds_haul_scanner(tmp_path: Path) -> None:
    source_snapshot = _write_snapshot(
        tmp_path,
        datetime(2026, 6, 28, 12, tzinfo=timezone.utc),
        [_order(1, 34, False, 100, STATION_ID)],
        region_id=REGION_ID,
    )
    dest_snapshot = _write_snapshot(
        tmp_path,
        datetime(2026, 6, 28, 12, tzinfo=timezone.utc),
        [_order(2, 34, True, 130, DEST_STATION_ID)],
        region_id=DEST_REGION_ID,
    )
    _write_market_db(
        tmp_path,
        source_snapshot,
        dest_snapshot,
        snapshot_regions=[REGION_ID, DEST_REGION_ID],
    )
    _write_sde_db(tmp_path)

    quotes = read_haul_quotes(
        Config(data_dir=tmp_path),
        REGION_ID,
        STATION_ID,
        DEST_REGION_ID,
        DEST_STATION_ID,
    )
    results = scan_haul_opportunities(quotes, Config())

    assert len(results) == 1
    assert results[0].type_id == 34


def test_read_haul_quotes_rejects_bad_volume_window(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        read_haul_quotes(
            Config(data_dir=tmp_path),
            REGION_ID,
            STATION_ID,
            DEST_REGION_ID,
            DEST_STATION_ID,
            volume_window_days=0,
        )


def test_read_price_series_returns_chronological_average_prices(tmp_path: Path) -> None:
    _write_price_history(
        tmp_path,
        [
            (REGION_ID, 34, date(2026, 1, 3), 130.0, 150.0, 100.0, 13, 3000),
            (REGION_ID, 34, date(2026, 1, 1), 110.0, 140.0, 90.0, 11, 1000),
            (REGION_ID, 34, date(2026, 1, 2), 120.0, 145.0, 95.0, 12, 2000),
        ],
    )

    series = read_price_series(Config(data_dir=tmp_path), REGION_ID, 34)

    assert series == [
        PricePoint(date="2026-01-01", price=110.0),
        PricePoint(date="2026-01-02", price=120.0),
        PricePoint(date="2026-01-03", price=130.0),
    ]


def test_read_price_series_excludes_null_average_rows(tmp_path: Path) -> None:
    _write_price_history(
        tmp_path,
        [
            (REGION_ID, 34, date(2026, 1, 1), 110.0, 140.0, 90.0, 11, 1000),
            (REGION_ID, 34, date(2026, 1, 2), None, 145.0, 95.0, 12, 2000),
            (REGION_ID, 34, date(2026, 1, 3), 130.0, 150.0, 100.0, 13, 3000),
        ],
    )

    series = read_price_series(Config(data_dir=tmp_path), REGION_ID, 34)

    assert [point.date for point in series] == ["2026-01-01", "2026-01-03"]
    assert [point.price for point in series] == [110.0, 130.0]


def test_read_price_series_returns_empty_for_unknown_type_region_and_empty_db(
    tmp_path: Path,
) -> None:
    _write_price_history(
        tmp_path,
        [(REGION_ID, 34, date(2026, 1, 1), 110.0, 140.0, 90.0, 11, 1000)],
    )
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with ensure_market_db(empty_dir / "market.duckdb"):
        pass

    assert read_price_series(Config(data_dir=tmp_path), REGION_ID, 99999) == []
    assert read_price_series(Config(data_dir=tmp_path), DEST_REGION_ID, 34) == []
    assert read_price_series(Config(data_dir=empty_dir), REGION_ID, 34) == []


def test_read_price_series_feeds_walkforward_engine(tmp_path: Path) -> None:
    _write_price_history(
        tmp_path,
        [
            (REGION_ID, 34, date(2026, 1, 1), 110.0, 140.0, 90.0, 11, 1000),
            (REGION_ID, 34, date(2026, 1, 2), 120.0, 145.0, 95.0, 12, 2000),
            (REGION_ID, 34, date(2026, 1, 3), 130.0, 150.0, 100.0, 13, 3000),
        ],
    )

    series = read_price_series(Config(data_dir=tmp_path), REGION_ID, 34)
    outcomes = run_forecaster_backtest(
        series,
        naive_persistence_forecast,
        Config(),
        horizon=1,
        warmup=1,
    )

    assert outcomes == []


def test_read_history_bars_returns_chronological_full_columns(tmp_path: Path) -> None:
    _write_price_history(
        tmp_path,
        [
            (REGION_ID, 34, date(2026, 1, 3), 130.0, 150.0, 100.0, 13, 3000),
            (REGION_ID, 34, date(2026, 1, 1), 110.0, 140.0, 90.0, 11, 1000),
            (REGION_ID, 34, date(2026, 1, 2), 120.0, 145.0, 95.0, 12, 2000),
        ],
    )

    bars = read_history_bars(Config(data_dir=tmp_path), REGION_ID, 34)

    assert bars == [
        HistoryBar(
            date="2026-01-01",
            average=110.0,
            highest=140.0,
            lowest=90.0,
            order_count=11,
            volume=1000,
        ),
        HistoryBar(
            date="2026-01-02",
            average=120.0,
            highest=145.0,
            lowest=95.0,
            order_count=12,
            volume=2000,
        ),
        HistoryBar(
            date="2026-01-03",
            average=130.0,
            highest=150.0,
            lowest=100.0,
            order_count=13,
            volume=3000,
        ),
    ]
    assert isinstance(bars[0].average, float)
    assert isinstance(bars[0].highest, float)
    assert isinstance(bars[0].lowest, float)
    assert isinstance(bars[0].order_count, int)
    assert isinstance(bars[0].volume, int)


def test_read_history_bars_excludes_null_average_rows(tmp_path: Path) -> None:
    _write_price_history(
        tmp_path,
        [
            (REGION_ID, 34, date(2026, 1, 1), 110.0, 140.0, 90.0, 11, 1000),
            (REGION_ID, 34, date(2026, 1, 2), None, 145.0, 95.0, 12, 2000),
            (REGION_ID, 34, date(2026, 1, 3), 130.0, 150.0, 100.0, 13, 3000),
        ],
    )

    bars = read_history_bars(Config(data_dir=tmp_path), REGION_ID, 34)

    assert [bar.date for bar in bars] == ["2026-01-01", "2026-01-03"]
    assert [bar.average for bar in bars] == [110.0, 130.0]


def test_read_history_bars_returns_empty_for_unknown_type_region_and_empty_db(
    tmp_path: Path,
) -> None:
    _write_price_history(
        tmp_path,
        [(REGION_ID, 34, date(2026, 1, 1), 110.0, 140.0, 90.0, 11, 1000)],
    )
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with ensure_market_db(empty_dir / "market.duckdb"):
        pass

    assert read_history_bars(Config(data_dir=tmp_path), REGION_ID, 99999) == []
    assert read_history_bars(Config(data_dir=tmp_path), DEST_REGION_ID, 34) == []
    assert read_history_bars(Config(data_dir=empty_dir), REGION_ID, 34) == []


def test_read_history_bars_feeds_feature_computation(tmp_path: Path) -> None:
    _write_price_history(
        tmp_path,
        [
            (REGION_ID, 34, date(2026, 1, 1), 110.0, 140.0, 90.0, 11, 1000),
            (REGION_ID, 34, date(2026, 1, 2), 120.0, 145.0, 95.0, 12, 2000),
            (REGION_ID, 34, date(2026, 1, 3), 130.0, 150.0, 100.0, 13, 3000),
        ],
    )

    bars = read_history_bars(Config(data_dir=tmp_path), REGION_ID, 34)
    rows = compute_features(bars, short_window=2, long_window=3)

    assert len(rows) == len(bars)
    assert rows[-1].date == "2026-01-03"
    assert rows[-1].price_zscore is not None


def _write_snapshot(
    data_dir: Path,
    snapshot_ts: datetime,
    orders: list[dict[str, object]],
    *,
    region_id: int = REGION_ID,
) -> Path:
    snapshot_path, _ = write_orders_snapshot(
        orders,
        region_id,
        snapshot_ts,
        data_dir / "snapshots",
    )
    return snapshot_path


def _write_market_db(
    data_dir: Path,
    *snapshot_paths: Path,
    snapshot_regions: list[int] | None = None,
) -> None:
    regions = snapshot_regions or [REGION_ID] * len(snapshot_paths)
    with ensure_market_db(data_dir / "market.duckdb") as connection:
        for index, (snapshot_path, region_id) in enumerate(zip(snapshot_paths, regions, strict=True)):
            snapshot_ts = datetime(2026, 6, 27 + index, 12, tzinfo=timezone.utc)
            record_ingest_run(
                connection,
                run_id=f"run-{index}",
                source="esi_orders",
                region_id=region_id,
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


def _write_history(data_dir: Path, region_id: int) -> None:
    with ensure_market_db(data_dir / "market.duckdb") as connection:
        connection.executemany(
            """
            INSERT INTO market_history (
                region_id, type_id, date, average, highest, lowest, order_count, volume
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (region_id, 34, date(2026, 6, 27), 100.0, 130.0, 90.0, 10, 1000),
                (region_id, 34, date(2026, 6, 28), 100.0, 130.0, 90.0, 10, 2000),
            ],
        )


def _write_price_history(
    data_dir: Path,
    rows: list[tuple[int, int, date, float | None, float, float, int, int]],
) -> None:
    with ensure_market_db(data_dir / "market.duckdb") as connection:
        connection.executemany(
            """
            INSERT INTO market_history (
                region_id, type_id, date, average, highest, lowest, order_count, volume
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def _write_sde_db(data_dir: Path) -> None:
    with duckdb.connect(str(data_dir / "sde.duckdb")) as connection:
        connection.execute(
            """
            CREATE TABLE sde_types (
                type_id BIGINT PRIMARY KEY,
                type_name TEXT,
                volume DOUBLE
            )
            """
        )
        connection.execute("INSERT INTO sde_types VALUES (?, ?, ?)", [34, "Tritanium", 0.01])


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
