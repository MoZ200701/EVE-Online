"""Read-only data quality checks for market storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class QualityCheck:
    name: str
    status: str
    detail: str


def run_quality_checks(
    conn,
    *,
    now=None,
    max_price_age_hours: float = 24.0,
    max_history_age_days: int = 3,
) -> list[QualityCheck]:
    now = _ensure_utc(now or datetime.now(timezone.utc))
    return [
        _check_stale_prices(conn, now, max_price_age_hours),
        _check_stale_history(conn, now, max_history_age_days),
        _check_price_anomalies(conn),
        _check_history_anomalies(conn),
        _check_failed_runs(conn),
    ]


def _check_stale_prices(conn, now: datetime, max_price_age_hours: float) -> QualityCheck:
    latest = conn.execute("SELECT max(snapshot_ts) FROM market_prices").fetchone()[0]
    if latest is None:
        return QualityCheck("stale_prices", "warn", "no price snapshots")

    latest = _ensure_utc(latest)
    age_h = (now - latest).total_seconds() / 3600
    status = "warn" if age_h > max_price_age_hours else "ok"
    return QualityCheck(
        "stale_prices",
        status,
        f"latest={latest.isoformat()} age={age_h:.1f}h",
    )


def _check_stale_history(conn, now: datetime, max_history_age_days: int) -> QualityCheck:
    latest = conn.execute("SELECT max(date) FROM market_history").fetchone()[0]
    if latest is None:
        return QualityCheck("stale_history", "warn", "no history rows")

    age_d = (now.date() - latest).days
    status = "warn" if age_d > max_history_age_days else "ok"
    return QualityCheck(
        "stale_history",
        status,
        f"latest={latest.isoformat()} age={age_d}d",
    )


def _check_price_anomalies(conn) -> QualityCheck:
    latest_ts = conn.execute("SELECT max(snapshot_ts) FROM market_prices").fetchone()[0]
    if latest_ts is None:
        return QualityCheck("price_anomalies", "ok", "no price snapshots")

    neg = conn.execute(
        "SELECT count(*) FROM market_prices "
        "WHERE snapshot_ts = ? AND adjusted_price < 0",
        [latest_ts],
    ).fetchone()[0]
    nul = conn.execute(
        "SELECT count(*) FROM market_prices "
        "WHERE snapshot_ts = ? AND adjusted_price IS NULL",
        [latest_ts],
    ).fetchone()[0]

    if neg > 0:
        status = "fail"
    elif nul > 0:
        status = "warn"
    else:
        status = "ok"

    return QualityCheck(
        "price_anomalies",
        status,
        f"negative={neg} null_adjusted={nul} (latest snapshot)",
    )


def _check_history_anomalies(conn) -> QualityCheck:
    bad = conn.execute(
        "SELECT count(*) FROM market_history "
        "WHERE highest < lowest OR average < 0 OR lowest < 0 OR highest < 0 "
        "OR volume < 0 OR order_count < 0"
    ).fetchone()[0]
    status = "fail" if bad > 0 else "ok"
    return QualityCheck("history_anomalies", status, f"{bad} invalid rows")


def _check_failed_runs(conn) -> QualityCheck:
    bad = conn.execute(
        "SELECT count(*) FROM ingest_runs WHERE status='failed'"
    ).fetchone()[0]
    if bad == 0:
        return QualityCheck("failed_runs", "ok", "no failed runs")

    source, error = conn.execute(
        "SELECT source, error FROM ingest_runs "
        "WHERE status='failed' ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return QualityCheck("failed_runs", "warn", f"{bad} failed runs; latest {source}: {error}")


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
