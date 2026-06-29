from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
from typer.testing import CliRunner

from evemarket.cli import app
from evemarket.store.schema import ensure_market_db
from evemarket.store.writers import record_ingest_run, write_orders_snapshot

SOURCE_REGION_ID = 10000002
SOURCE_STATION_ID = 60003760
DEST_REGION_ID = 10000043
DEST_STATION_ID = 60008494


def test_haul_command_prints_haul_table(tmp_path: Path) -> None:
    _write_config(tmp_path)
    source_snapshot = _write_snapshot(
        tmp_path,
        SOURCE_REGION_ID,
        [
            _order(1, 34, False, 100, SOURCE_STATION_ID),
            _order(2, 35, False, 200, SOURCE_STATION_ID),
        ],
    )
    dest_snapshot = _write_snapshot(
        tmp_path,
        DEST_REGION_ID,
        [
            _order(3, 34, True, 140, DEST_STATION_ID),
            _order(4, 36, True, 300, DEST_STATION_ID),
        ],
    )
    _write_market_db(tmp_path, source_snapshot, dest_snapshot)
    _write_sde_db(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "haul",
            "--config",
            str(tmp_path / "config.toml"),
            "--source-region",
            str(SOURCE_REGION_ID),
            "--dest-region",
            str(DEST_REGION_ID),
            "--dest-station",
            str(DEST_STATION_ID),
        ],
    )

    assert result.exit_code == 0
    assert (
        "Source: 10000002/60003760  Dest: 10000043/60008494  Quotes: 1"
        in result.output
    )
    assert "type_id" in result.output
    assert "Tritanium" in result.output
    assert "140.00" in result.output
    assert "36" not in result.output


def test_haul_command_requires_dest_region_and_station(tmp_path: Path) -> None:
    _write_config(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "haul",
            "--config",
            str(tmp_path / "config.toml"),
        ],
    )

    assert result.exit_code != 0
    assert "--dest-region and --dest-station are required." in result.output


def test_haul_command_no_snapshot_message(tmp_path: Path) -> None:
    _write_config(tmp_path)
    with ensure_market_db(tmp_path / "market.duckdb"):
        pass

    result = CliRunner().invoke(
        app,
        [
            "haul",
            "--config",
            str(tmp_path / "config.toml"),
            "--dest-region",
            str(DEST_REGION_ID),
            "--dest-station",
            str(DEST_STATION_ID),
        ],
    )

    assert result.exit_code == 0
    assert (
        "No market snapshot found for the source/destination regions. "
        "Run ingest-orders for both first."
    ) in result.output


def test_haul_command_filter_excludes_all(tmp_path: Path) -> None:
    _write_config(tmp_path)
    source_snapshot = _write_snapshot(
        tmp_path,
        SOURCE_REGION_ID,
        [_order(1, 34, False, 100, SOURCE_STATION_ID)],
    )
    dest_snapshot = _write_snapshot(
        tmp_path,
        DEST_REGION_ID,
        [_order(2, 34, True, 140, DEST_STATION_ID)],
    )
    _write_market_db(tmp_path, source_snapshot, dest_snapshot)
    _write_sde_db(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "haul",
            "--config",
            str(tmp_path / "config.toml"),
            "--dest-region",
            str(DEST_REGION_ID),
            "--dest-station",
            str(DEST_STATION_ID),
            "--min-roi",
            "999",
        ],
    )

    assert result.exit_code == 0
    assert "No haul opportunities met the filters." in result.output


def test_haul_command_limit_one_prints_one_data_row(tmp_path: Path) -> None:
    _write_config(tmp_path)
    source_snapshot = _write_snapshot(
        tmp_path,
        SOURCE_REGION_ID,
        [
            _order(1, 34, False, 100, SOURCE_STATION_ID),
            _order(2, 36, False, 100, SOURCE_STATION_ID),
        ],
    )
    dest_snapshot = _write_snapshot(
        tmp_path,
        DEST_REGION_ID,
        [
            _order(3, 34, True, 140, DEST_STATION_ID),
            _order(4, 36, True, 180, DEST_STATION_ID),
        ],
    )
    _write_market_db(tmp_path, source_snapshot, dest_snapshot)
    _write_sde_db(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "haul",
            "--config",
            str(tmp_path / "config.toml"),
            "--dest-region",
            str(DEST_REGION_ID),
            "--dest-station",
            str(DEST_STATION_ID),
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
    region_id: int,
    orders: list[dict[str, object]],
) -> Path:
    snapshot_path, _ = write_orders_snapshot(
        orders,
        region_id,
        datetime(2026, 6, 29, 12, tzinfo=timezone.utc),
        data_dir / "snapshots",
    )
    return snapshot_path


def _write_market_db(
    data_dir: Path,
    source_snapshot: Path,
    dest_snapshot: Path,
) -> None:
    snapshot_ts = datetime(2026, 6, 29, 12, tzinfo=timezone.utc)
    with ensure_market_db(data_dir / "market.duckdb") as connection:
        record_ingest_run(
            connection,
            run_id="source-run",
            source="esi_orders",
            region_id=SOURCE_REGION_ID,
            snapshot_ts=snapshot_ts,
            started_at=snapshot_ts,
            finished_at=snapshot_ts,
            status="success",
            order_count=2,
            pages=1,
            snapshot_path=str(source_snapshot),
        )
        record_ingest_run(
            connection,
            run_id="dest-run",
            source="esi_orders",
            region_id=DEST_REGION_ID,
            snapshot_ts=snapshot_ts,
            started_at=snapshot_ts,
            finished_at=snapshot_ts,
            status="success",
            order_count=2,
            pages=1,
            snapshot_path=str(dest_snapshot),
        )
        connection.executemany(
            """
            INSERT INTO market_history (
                region_id, type_id, date, average, highest, lowest, order_count, volume
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    DEST_REGION_ID,
                    34,
                    date(2026, 6, 29),
                    130.0,
                    140.0,
                    120.0,
                    10,
                    1000,
                ),
                (
                    DEST_REGION_ID,
                    36,
                    date(2026, 6, 29),
                    170.0,
                    180.0,
                    160.0,
                    10,
                    2000,
                ),
            ],
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
        connection.execute("INSERT INTO sde_types VALUES (?, ?, ?)", [36, "#36", 0.01])


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
        "issued": datetime(2026, 6, 29, tzinfo=timezone.utc),
    }
