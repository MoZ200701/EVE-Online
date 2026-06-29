from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from evemarket.store.schema import ensure_market_db
from evemarket.store.writers import record_ingest_run, write_orders_snapshot

REGION_ID = 10000002
STATION_ID = 60003760
DEST_REGION_ID = 10000043
DEST_STATION_ID = 60008494


def test_ui_station_trade_empty_state(tmp_path: Path) -> None:
    _write_config(tmp_path)

    at = AppTest.from_file(_app_path())
    at.session_state["config_path"] = str(tmp_path / "config.toml")
    at.run()

    assert not at.exception
    assert any("No market snapshot" in info.value for info in at.info)


def test_ui_station_trade_happy_path(tmp_path: Path) -> None:
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

    at = AppTest.from_file(_app_path())
    at.session_state["config_path"] = str(tmp_path / "config.toml")
    at.run()

    assert not at.exception
    assert len(at.dataframe) == 1
    dataframe_text = str(at.dataframe[0].value)
    assert "34" in dataframe_text
    assert "Tritanium" in dataframe_text
    assert "35" not in dataframe_text


def test_ui_station_trade_filter_excludes_all(tmp_path: Path) -> None:
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

    at = AppTest.from_file(_app_path())
    at.session_state["config_path"] = str(tmp_path / "config.toml")
    at.session_state["min_roi"] = 999.0
    at.run()

    assert not at.exception
    assert any("No station-trade opportunities" in info.value for info in at.info)


def test_ui_haul_prompts_for_destination(tmp_path: Path) -> None:
    _write_config(tmp_path)

    at = AppTest.from_file(_app_path())
    at.session_state["config_path"] = str(tmp_path / "config.toml")
    at.run()

    assert not at.exception
    assert any("Enter a destination" in info.value for info in at.info)


def test_ui_haul_happy_path(tmp_path: Path) -> None:
    _write_config(tmp_path)
    source_snapshot = _write_snapshot(
        tmp_path,
        [
            _order(1, 34, False, 100, STATION_ID),
            _order(2, 35, False, 200, STATION_ID),
        ],
    )
    dest_snapshot = _write_snapshot(
        tmp_path,
        [
            _order(3, 34, True, 130, DEST_STATION_ID),
            _order(4, 36, True, 300, DEST_STATION_ID),
        ],
        region_id=DEST_REGION_ID,
    )
    _write_market_db(tmp_path, source_snapshot, dest_snapshot=dest_snapshot)
    _write_sde_db(tmp_path)

    at = AppTest.from_file(_app_path())
    at.session_state["config_path"] = str(tmp_path / "config.toml")
    at.session_state["dest_region"] = DEST_REGION_ID
    at.session_state["dest_station"] = DEST_STATION_ID
    at.run()

    assert not at.exception
    assert len(at.dataframe) == 1
    dataframe_text = str(at.dataframe[0].value)
    assert "34" in dataframe_text
    assert "Tritanium" in dataframe_text
    assert "days_to_sell" in dataframe_text


def test_ui_haul_no_dest_snapshot_message(tmp_path: Path) -> None:
    _write_config(tmp_path)
    source_snapshot = _write_snapshot(
        tmp_path,
        [_order(1, 34, False, 100, STATION_ID)],
    )
    _write_market_db(tmp_path, source_snapshot)
    _write_sde_db(tmp_path)

    at = AppTest.from_file(_app_path())
    at.session_state["config_path"] = str(tmp_path / "config.toml")
    at.session_state["dest_region"] = DEST_REGION_ID
    at.session_state["dest_station"] = DEST_STATION_ID
    at.run()

    assert not at.exception
    assert any(
        "No market snapshot found for the source/destination regions" in info.value
        for info in at.info
    )


def test_ui_haul_filter_excludes_all(tmp_path: Path) -> None:
    _write_config(tmp_path)
    source_snapshot = _write_snapshot(
        tmp_path,
        [_order(1, 34, False, 100, STATION_ID)],
    )
    dest_snapshot = _write_snapshot(
        tmp_path,
        [_order(2, 34, True, 130, DEST_STATION_ID)],
        region_id=DEST_REGION_ID,
    )
    _write_market_db(tmp_path, source_snapshot, dest_snapshot=dest_snapshot)
    _write_sde_db(tmp_path)

    at = AppTest.from_file(_app_path())
    at.session_state["config_path"] = str(tmp_path / "config.toml")
    at.session_state["dest_region"] = DEST_REGION_ID
    at.session_state["dest_station"] = DEST_STATION_ID
    at.session_state["min_total_profit"] = 1e15
    at.run()

    assert not at.exception
    assert any("No haul opportunities" in info.value for info in at.info)


def _app_path() -> str:
    return str(Path(__file__).parents[1] / "src" / "evemarket" / "ui" / "app.py")


def _write_config(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text(
        f'data_dir = "{tmp_path.as_posix()}"\n',
        encoding="utf-8",
    )


def _write_snapshot(
    data_dir: Path,
    orders: list[dict[str, object]],
    *,
    region_id: int = REGION_ID,
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
    snapshot_path: Path,
    *,
    dest_snapshot: Path | None = None,
) -> None:
    snapshot_ts = datetime(2026, 6, 29, 12, tzinfo=timezone.utc)
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
        if dest_snapshot is not None:
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
                (REGION_ID, 34, date(2026, 6, 29), 100.0, 120.0, 90.0, 10, 1000),
                (
                    DEST_REGION_ID,
                    34,
                    date(2026, 6, 29),
                    120.0,
                    130.0,
                    110.0,
                    10,
                    1000,
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
