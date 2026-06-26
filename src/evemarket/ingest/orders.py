"""Order-book snapshot ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from evemarket.config import Config
from evemarket.esi.client import ESIClient
from evemarket.esi.models import MarketOrder
from evemarket.store.schema import ensure_market_db
from evemarket.store.writers import record_ingest_run, write_orders_snapshot


@dataclass(frozen=True)
class IngestResult:
    run_id: str
    region_id: int
    snapshot_ts: datetime
    order_count: int
    pages: int
    snapshot_path: Path | None
    status: str
    esi_expires: datetime | None


async def ingest_orders(
    client: ESIClient,
    config: Config,
    region_id: int,
    *,
    now: datetime | None = None,
) -> IngestResult:
    """Fetch and persist one regional order-book snapshot."""

    snapshot_ts = _ensure_utc(now or datetime.now(timezone.utc))
    started_at = datetime.now(timezone.utc)
    run_id = str(uuid4())
    data_dir = config.data_dir.expanduser()
    market_db_path = data_dir / "market.duckdb"
    snapshots_root = data_dir / "snapshots"
    path = f"/latest/markets/{region_id}/orders/"
    params = {"order_type": "all", "page": 1}

    pages = 0
    esi_expires = None

    try:
        first_page = await client.get(path, params=params)
        pages = first_page.pages or 1
        esi_expires = first_page.expires
        orders = await client.get_paginated(path, params=params)
        _validate_sample(orders)
        snapshot_path, order_count = write_orders_snapshot(
            orders,
            region_id,
            snapshot_ts,
            snapshots_root,
        )

        with ensure_market_db(market_db_path) as connection:
            record_ingest_run(
                connection,
                run_id=run_id,
                source="esi_orders",
                region_id=region_id,
                snapshot_ts=snapshot_ts,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                status="success",
                order_count=order_count,
                pages=pages,
                esi_expires=esi_expires,
                snapshot_path=str(snapshot_path),
                error=None,
            )

        return IngestResult(
            run_id=run_id,
            region_id=region_id,
            snapshot_ts=snapshot_ts,
            order_count=order_count,
            pages=pages,
            snapshot_path=snapshot_path,
            status="success",
            esi_expires=esi_expires,
        )
    except Exception as exc:
        with ensure_market_db(market_db_path) as connection:
            record_ingest_run(
                connection,
                run_id=run_id,
                source="esi_orders",
                region_id=region_id,
                snapshot_ts=snapshot_ts,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                status="failed",
                order_count=0,
                pages=pages,
                esi_expires=esi_expires,
                snapshot_path=None,
                error=str(exc),
            )
        raise


def _validate_sample(orders: list[dict]) -> None:
    for order in orders[:50]:
        MarketOrder.model_validate(order)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
