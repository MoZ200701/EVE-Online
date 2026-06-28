from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
from typer.testing import CliRunner

from evemarket.cli import app
from evemarket.store.schema import ensure_market_db
from evemarket.store.writers import record_ingest_run, write_orders_snapshot

REGION_ID = 10000002
STATION_ID = 60003760


def test_scan_command_prints_station_trade_table(tmp_path: Path) -> None:
    _write_config(tmp_path)
    snapshot_path = _write_snapshot(
        tmp_path,
        [
            _order(1, 34, True, 100, STATION_ID),
            _order(2, 34, False, 120, STATION_ID),
            _order(3, 35, False, 200, STATION_ID),
        ],
    )
    _write_market_db(tmp_path, snapshot_path)
    _write_sde_db(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "scan",
            "--config",
            str(tmp_path / "config.toml"),
            "--region",
            str(REGION_ID),
        ],
    )

    assert result.exit_code == 0
    assert "Region: 10000002  Station: 60003760  Quotes: 2" in result.output
    assert "Tritanium" in result.output
    assert "34" in result.output
    assert "35" not in result.output


def test_scan_command_no_snapshot_message(tmp_path: Path) -> None:
    _write_config(tmp_path)
    with ensure_market_db(tmp_path / "market.duckdb"):
        pass

    result = CliRunner().invoke(
        app,
        [
            "scan",
            "--config",
            str(tmp_path / "config.toml"),
            "--region",
            str(REGION_ID),
        ],
    )

    assert result.exit_code == 0
    assert "No market snapshot found for region 10000002" in result.output


def test_scan_command_filter_excludes_all(tmp_path: Path) -> None:
    _write_config(tmp_path)
    snapshot_path = _write_snapshot(
        tmp_path,
        [
            _order(1, 34, True, 100, STATION_ID),
            _order(2, 34, False, 120, STATION_ID),
        ],
    )
    _write_market_db(tmp_path, snapshot_path)
    _write_sde_db(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "scan",
            "--config",
            str(tmp_path / "config.toml"),
            "--region",
            str(REGION_ID),
            "--min-roi",
            "999",
        ],
    )

    assert result.exit_code == 0
    assert "No station-trade opportunities met the filters." in result.output


def test_scan_command_limit_one_prints_one_data_row(tmp_path: Path) -> None:
    _write_config(tmp_path)
    snapshot_path = _write_snapshot(
        tmp_path,
        [
            _order(1, 34, True, 100, STATION_ID),
            _order(2, 34, False, 120, STATION_ID),
            _order(3, 36, True, 100, STATION_ID),
            _order(4, 36, False, 130, STATION_ID),
        ],
    )
    _write_market_db(tmp_path, snapshot_path)
    _write_sde_db(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "scan",
            "--config",
            str(tmp_path / "config.toml"),
            "--region",
            str(REGION_ID),
            "--limit",
            "1",
        ],
    )

    assert result.exit_code == 0
    assert "Tritanium" not in result.output
    assert "#36" in result.output


def _write_config(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text(
        f'data_dir = "{tmp_path.as_posix()}"\n',
        encoding="utf-8",
    )


def _write_snapshot(
    data_dir: Path,
    orders: list[dict[str, object]],
) -> Path:
    snapshot_path, _ = write_orders_snapshot(
        orders,
        REGION_ID,
        datetime(2026, 6, 28, 12, tzinfo=timezone.utc),
        data_dir / "snapshots",
    )
    return snapshot_path


def _write_market_db(data_dir: Path, snapshot_path: Path) -> None:
    snapshot_ts = datetime(2026, 6, 28, 12, tzinfo=timezone.utc)
    with ensure_market_db(data_dir / "market.duckdb") as connection:
        record_ingest_run(
            connection,
            run_id="run-1",
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
                (REGION_ID, 34, date(2026, 6, 28), 100.0, 120.0, 90.0, 10, 1000),
                (REGION_ID, 36, date(2026, 6, 28), 100.0, 130.0, 90.0, 10, 2000),
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
