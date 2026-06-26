"""Market prices ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from evemarket.config import Config
from evemarket.esi.client import ESIClient
from evemarket.esi.models import MarketPrice
from evemarket.store.schema import ensure_market_db
from evemarket.store.writers import record_ingest_run, write_prices


@dataclass(frozen=True)
class PricesIngestResult:
    run_id: str
    price_count: int
    status: str
    esi_expires: datetime | None
    snapshot_ts: datetime


async def ingest_prices(
    client: ESIClient,
    config: Config,
    *,
    now: datetime | None = None,
) -> PricesIngestResult:
    """Fetch and persist one global market-prices snapshot."""

    snapshot_ts = _ensure_utc(now or datetime.now(timezone.utc))
    started_at = datetime.now(timezone.utc)
    run_id = str(uuid4())
    market_db_path = config.data_dir.expanduser() / "market.duckdb"
    esi_expires = None

    try:
        response = await client.get("/latest/markets/prices/")
        esi_expires = response.expires
        prices = list(response.data)
        _validate_sample(prices)

        with ensure_market_db(market_db_path) as connection:
            price_count = write_prices(connection, prices, snapshot_ts)
            record_ingest_run(
                connection,
                run_id=run_id,
                source="esi_prices",
                region_id=None,
                snapshot_ts=snapshot_ts,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                status="success",
                order_count=price_count,
                pages=1,
                esi_expires=esi_expires,
                snapshot_path=None,
                error=None,
            )

        return PricesIngestResult(
            run_id=run_id,
            price_count=price_count,
            status="success",
            esi_expires=esi_expires,
            snapshot_ts=snapshot_ts,
        )
    except Exception as exc:
        with ensure_market_db(market_db_path) as connection:
            record_ingest_run(
                connection,
                run_id=run_id,
                source="esi_prices",
                region_id=None,
                snapshot_ts=snapshot_ts,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                status="failed",
                order_count=0,
                pages=1,
                esi_expires=esi_expires,
                snapshot_path=None,
                error=str(exc),
            )
        raise


def _validate_sample(prices: list[dict]) -> None:
    for price in prices[:50]:
        MarketPrice.model_validate(price)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
