"""Command-line interface for EVE Market Tool."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import typer

from evemarket.config import load_config
from evemarket.esi.client import ESIClient
from evemarket.esi.models import MarketOrder
from evemarket.ingest.backfill import backfill_history_everef
from evemarket.ingest.history import ingest_history
from evemarket.ingest.orders import ingest_orders
from evemarket.sde.load import connect, download_sde, load_sde, table_counts

app = typer.Typer(help="EVE Market Tool.")


@app.callback()
def main() -> None:
    """EVE Market Tool."""


@app.command()
def info(
    config: Path = typer.Option(
        Path("config.toml"),
        "--config",
        "-c",
        help="Path to a TOML configuration file.",
    ),
) -> None:
    """Print configuration wiring details."""

    loaded_config = load_config(config)
    data_dir = loaded_config.data_dir.expanduser().resolve()
    user_agent_set = bool(loaded_config.user_agent.strip())

    typer.echo(f"Data dir: {data_dir}")
    typer.echo(f"Tracked regions: {loaded_config.tracked_regions}")
    typer.echo(f"User-Agent set: {'yes' if user_agent_set else 'no'}")
    if "REPLACE_ME" in loaded_config.user_agent:
        typer.echo("WARNING: User-Agent still contains REPLACE_ME contact placeholder.")


@app.command("sde-load")
def sde_load(
    config: Path = typer.Option(
        Path("config.toml"),
        "--config",
        "-c",
        help="Path to a TOML configuration file.",
    ),
) -> None:
    """Download Fuzzwork SDE CSVs and load them into DuckDB."""

    loaded_config = load_config(config)
    data_dir = loaded_config.data_dir.expanduser()
    cache_dir = data_dir / "sde_cache"
    duckdb_path = data_dir / "sde.duckdb"

    csv_files = download_sde(cache_dir, user_agent=loaded_config.user_agent)
    load_sde(duckdb_path, csv_files)

    with connect(duckdb_path) as connection:
        for table_name, count in table_counts(connection).items():
            typer.echo(f"{table_name}: {count}")


@app.command("sde-info")
def sde_info(
    config: Path = typer.Option(
        Path("config.toml"),
        "--config",
        "-c",
        help="Path to a TOML configuration file.",
    ),
) -> None:
    """Print SDE table counts and basic sanity lookups."""

    loaded_config = load_config(config)
    duckdb_path = loaded_config.data_dir.expanduser() / "sde.duckdb"

    with connect(duckdb_path) as connection:
        for table_name, count in table_counts(connection).items():
            typer.echo(f"{table_name}: {count}")

        tritanium = connection.execute(
            "SELECT type_name FROM sde_types WHERE type_id = 34"
        ).fetchone()
        the_forge = connection.execute(
            "SELECT region_name FROM sde_regions WHERE region_id = 10000002"
        ).fetchone()

    typer.echo(f"type_id 34: {tritanium[0] if tritanium else '<missing>'}")
    typer.echo(f"region_id 10000002: {the_forge[0] if the_forge else '<missing>'}")


@app.command("esi-check")
def esi_check(
    config: Path = typer.Option(
        Path("config.toml"),
        "--config",
        "-c",
        help="Path to a TOML configuration file.",
    ),
    region: int | None = typer.Option(
        None,
        "--region",
        help="EVE region ID. Defaults to the first configured tracked region.",
    ),
    limit: int = typer.Option(
        5,
        "--limit",
        min=1,
        help="Number of sample orders to print.",
    ),
) -> None:
    """Fetch page 1 of public regional market orders from ESI."""

    loaded_config = load_config(config)
    selected_region = region or loaded_config.tracked_regions[0]
    asyncio.run(_run_esi_check(loaded_config, selected_region, limit))


async def _run_esi_check(config, region: int, limit: int) -> None:
    async with ESIClient(config=config) as client:
        response = await client.get(
            f"/latest/markets/{region}/orders/",
            params={"order_type": "all", "page": 1},
        )

    orders = [MarketOrder.model_validate(order) for order in response.data]
    typer.echo(f"Region: {region}")
    typer.echo(f"Page 1 orders: {len(orders)}")
    typer.echo(f"X-Pages: {response.pages}")

    for order in orders[:limit]:
        side = "buy" if order.is_buy_order else "sell"
        typer.echo(
            "Order "
            f"{order.order_id}: type={order.type_id} side={side} "
            f"price={order.price} remain={order.volume_remain}/{order.volume_total}"
        )


@app.command("ingest-orders")
def ingest_orders_command(
    config: Path = typer.Option(
        Path("config.toml"),
        "--config",
        "-c",
        help="Path to a TOML configuration file.",
    ),
    region: int | None = typer.Option(
        None,
        "--region",
        help="EVE region ID. Defaults to the first configured tracked region.",
    ),
) -> None:
    """Fetch and store one full regional market order snapshot."""

    loaded_config = load_config(config)
    selected_region = region or loaded_config.tracked_regions[0]
    result = asyncio.run(_run_ingest_orders(loaded_config, selected_region))

    typer.echo(f"Region: {result.region_id}")
    typer.echo(f"Status: {result.status}")
    typer.echo(f"Run ID: {result.run_id}")
    typer.echo(f"Pages: {result.pages}")
    typer.echo(f"Order count: {result.order_count}")
    typer.echo(f"Snapshot path: {result.snapshot_path}")
    typer.echo(f"ESI expires: {result.esi_expires}")


async def _run_ingest_orders(config, region: int):
    async with ESIClient(config=config) as client:
        return await ingest_orders(client, config, region)


@app.command("ingest-history")
def ingest_history_command(
    config: Path = typer.Option(
        Path("config.toml"),
        "--config",
        "-c",
        help="Path to a TOML configuration file.",
    ),
    region: int | None = typer.Option(
        None,
        "--region",
        help="EVE region ID. Defaults to the first configured tracked region.",
    ),
    type_ids: list[int] | None = typer.Option(
        None,
        "--type",
        help="EVE type ID to fetch. Repeat for multiple types.",
    ),
) -> None:
    """Fetch and store ESI daily market history."""

    loaded_config = load_config(config)
    selected_region = region or loaded_config.tracked_regions[0]
    selected_type_ids = type_ids or [34]
    result = asyncio.run(
        _run_ingest_history(loaded_config, selected_region, selected_type_ids)
    )

    typer.echo(f"Region: {result.region_id}")
    typer.echo(f"Status: {result.status}")
    typer.echo(f"Run ID: {result.run_id}")
    typer.echo(f"Types fetched: {result.types_fetched}")
    typer.echo(f"Type IDs: {result.type_ids}")
    typer.echo(f"Day count: {result.day_count}")
    typer.echo(f"ESI expires: {result.esi_expires}")


async def _run_ingest_history(config, region: int, type_ids: list[int]):
    async with ESIClient(config=config) as client:
        return await ingest_history(client, config, region, type_ids)


@app.command("backfill-history")
def backfill_history_command(
    config: Path = typer.Option(
        Path("config.toml"),
        "--config",
        "-c",
        help="Path to a TOML configuration file.",
    ),
    region: int | None = typer.Option(
        None,
        "--region",
        help="EVE region ID. Defaults to the first configured tracked region.",
    ),
    start: str | None = typer.Option(
        None,
        "--start",
        help="Start date, inclusive, as YYYY-MM-DD.",
    ),
    end: str | None = typer.Option(
        None,
        "--end",
        help="End date, inclusive, as YYYY-MM-DD.",
    ),
) -> None:
    """Backfill market history from everef.net static dumps."""

    loaded_config = load_config(config)
    selected_region = region or loaded_config.tracked_regions[0]
    start_date, end_date = _parse_backfill_dates(start, end)
    result = backfill_history_everef(
        loaded_config,
        selected_region,
        start_date,
        end_date,
    )

    typer.echo(f"Region: {result.region_id}")
    typer.echo(f"Status: {result.status}")
    typer.echo(f"Run ID: {result.run_id}")
    typer.echo(f"Start: {result.start_date}")
    typer.echo(f"End: {result.end_date}")
    typer.echo(f"Days fetched: {result.days_fetched}")
    typer.echo(f"Days missing: {result.days_missing}")
    typer.echo(f"Row count: {result.row_count}")


def _parse_backfill_dates(start: str | None, end: str | None) -> tuple[date, date]:
    if start is None and end is None:
        end_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        return end_date - timedelta(days=2), end_date

    if start is None or end is None:
        raise typer.BadParameter("--start and --end must be provided together.")

    return date.fromisoformat(start), date.fromisoformat(end)
