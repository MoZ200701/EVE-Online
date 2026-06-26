"""Daily market-history ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from evemarket.config import Config
from evemarket.esi.client import ESIClient
from evemarket.esi.models import MarketHistoryDay
from evemarket.store.schema import ensure_market_db
from evemarket.store.writers import record_ingest_run, write_history


@dataclass(frozen=True)
class HistoryIngestResult:
    run_id: str
    region_id: int
    type_ids: list[int]
    day_count: int
    types_fetched: int
    status: str
    esi_expires: datetime | None


async def ingest_history(
    client: ESIClient,
    config: Config,
    region_id: int,
    type_ids: list[int],
    *,
    now: datetime | None = None,
) -> HistoryIngestResult:
    """Fetch and persist ESI daily market history for selected type IDs."""

    snapshot_ts = _ensure_utc(now or datetime.now(timezone.utc))
    started_at = datetime.now(timezone.utc)
    run_id = str(uuid4())
    market_db_path = config.data_dir.expanduser() / "market.duckdb"
    day_count = 0
    types_fetched = 0
    esi_expires = None

    try:
        with ensure_market_db(market_db_path) as connection:
            for type_id in type_ids:
                response = await client.get(
                    f"/latest/markets/{region_id}/history/",
                    params={"type_id": type_id},
                )
                if esi_expires is None:
                    esi_expires = response.expires

                days = list(response.data)
                _validate_sample(days)
                day_count += write_history(connection, region_id, type_id, days)
                types_fetched += 1

            record_ingest_run(
                connection,
                run_id=run_id,
                source="esi_history",
                region_id=region_id,
                snapshot_ts=snapshot_ts,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                status="success",
                order_count=day_count,
                pages=len(type_ids),
                esi_expires=esi_expires,
                snapshot_path=None,
                error=None,
            )

        return HistoryIngestResult(
            run_id=run_id,
            region_id=region_id,
            type_ids=type_ids,
            day_count=day_count,
            types_fetched=types_fetched,
            status="success",
            esi_expires=esi_expires,
        )
    except Exception as exc:
        with ensure_market_db(market_db_path) as connection:
            record_ingest_run(
                connection,
                run_id=run_id,
                source="esi_history",
                region_id=region_id,
                snapshot_ts=snapshot_ts,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                status="failed",
                order_count=0,
                pages=len(type_ids),
                esi_expires=esi_expires,
                snapshot_path=None,
                error=str(exc),
            )
        raise


def _validate_sample(days: list[dict]) -> None:
    for day in days[:50]:
        MarketHistoryDay.model_validate(day)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
