from __future__ import annotations

from datetime import datetime, timedelta, timezone

from evemarket.store.quality import run_quality_checks
from evemarket.store.schema import ensure_market_db
from evemarket.store.writers import record_ingest_run, write_history_bulk, write_prices


NOW = datetime(2026, 6, 26, 12, 0, tzinfo=timezone.utc)


def _statuses(checks):
    return {check.name: check.status for check in checks}


def _details(checks):
    return {check.name: check.detail for check in checks}


def _connect(tmp_path):
    return ensure_market_db(tmp_path / "market.duckdb")


def _write_valid_history(conn, *, days_ago: int = 0) -> None:
    write_history_bulk(
        conn,
        [
            {
                "date": (NOW - timedelta(days=days_ago)).date(),
                "average": 10.0,
                "highest": 12.0,
                "lowest": 8.0,
                "order_count": 5,
                "volume": 100,
                "region_id": 10000002,
                "type_id": 34,
            }
        ],
    )


def test_quality_checks_all_good(tmp_path) -> None:
    with _connect(tmp_path) as conn:
        write_prices(
            conn,
            [{"type_id": 34, "adjusted_price": 5.0, "average_price": None}],
            NOW,
        )
        _write_valid_history(conn)

        checks = run_quality_checks(conn, now=NOW)

    assert [check.name for check in checks] == [
        "stale_prices",
        "stale_history",
        "price_anomalies",
        "history_anomalies",
        "failed_runs",
    ]
    assert set(_statuses(checks).values()) == {"ok"}


def test_quality_checks_warn_on_stale_prices_and_history(tmp_path) -> None:
    with _connect(tmp_path) as conn:
        write_prices(
            conn,
            [{"type_id": 34, "adjusted_price": 5.0, "average_price": 5.0}],
            NOW - timedelta(hours=48),
        )
        _write_valid_history(conn, days_ago=10)

        statuses = _statuses(run_quality_checks(conn, now=NOW))

    assert statuses["stale_prices"] == "warn"
    assert statuses["stale_history"] == "warn"


def test_price_anomalies_fail_on_negative_adjusted_price(tmp_path) -> None:
    with _connect(tmp_path) as conn:
        write_prices(
            conn,
            [{"type_id": 34, "adjusted_price": -1.0, "average_price": None}],
            NOW,
        )

        statuses = _statuses(run_quality_checks(conn, now=NOW))

    assert statuses["price_anomalies"] == "fail"


def test_price_anomalies_warn_on_null_adjusted_price(tmp_path) -> None:
    with _connect(tmp_path) as conn:
        write_prices(
            conn,
            [{"type_id": 34, "adjusted_price": None, "average_price": 5.0}],
            NOW,
        )

        statuses = _statuses(run_quality_checks(conn, now=NOW))

    assert statuses["price_anomalies"] == "warn"


def test_price_anomalies_ignore_null_average_price(tmp_path) -> None:
    with _connect(tmp_path) as conn:
        write_prices(
            conn,
            [{"type_id": 34, "adjusted_price": 5.0, "average_price": None}],
            NOW,
        )

        statuses = _statuses(run_quality_checks(conn, now=NOW))

    assert statuses["price_anomalies"] == "ok"


def test_history_anomalies_fail_on_highest_below_lowest(tmp_path) -> None:
    with _connect(tmp_path) as conn:
        write_history_bulk(
            conn,
            [
                {
                    "date": NOW.date(),
                    "average": 10.0,
                    "highest": 8.0,
                    "lowest": 12.0,
                    "order_count": 5,
                    "volume": 100,
                    "region_id": 10000002,
                    "type_id": 34,
                }
            ],
        )

        statuses = _statuses(run_quality_checks(conn, now=NOW))

    assert statuses["history_anomalies"] == "fail"


def test_failed_runs_warn_with_source_and_error_detail(tmp_path) -> None:
    with _connect(tmp_path) as conn:
        record_ingest_run(
            conn,
            run_id="failed-run",
            source="esi_prices",
            region_id=None,
            snapshot_ts=NOW,
            started_at=NOW,
            finished_at=NOW,
            status="failed",
            order_count=0,
            pages=0,
            error="boom",
        )

        checks = run_quality_checks(conn, now=NOW)

    assert _statuses(checks)["failed_runs"] == "warn"
    assert "esi_prices: boom" in _details(checks)["failed_runs"]


def test_empty_db_warns_for_missing_prices_and_history_only(tmp_path) -> None:
    with _connect(tmp_path) as conn:
        statuses = _statuses(run_quality_checks(conn, now=NOW))

    assert statuses == {
        "stale_prices": "warn",
        "stale_history": "warn",
        "price_anomalies": "ok",
        "history_anomalies": "ok",
        "failed_runs": "ok",
    }
