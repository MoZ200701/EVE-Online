"""Command-line interface for EVE Market Tool."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import typer

from evemarket.config import load_config
from evemarket.esi.client import ESIClient
from evemarket.esi.models import MarketOrder
from evemarket.ingest.backfill import backfill_history_everef
from evemarket.ingest.history import ingest_history
from evemarket.ingest.orders import ingest_orders
from evemarket.ingest.prices import ingest_prices
from evemarket.scheduler import build_scheduler
from evemarket.sde.load import connect, download_sde, load_sde, table_counts
from evemarket.analytics.backtest import (
    BacktestMetrics,
    compute_metrics,
    Forecast,
    naive_persistence_forecast,
    PricePoint,
    seasonal_naive_forecast,
)
from evemarket.analytics.haul import HaulResult, scan_haul_opportunities
from evemarket.analytics.station_trade import StationTradeResult, scan_station_trades
from evemarket.analytics.walkforward import (
    buy_and_hold_outcomes,
    run_forecaster_backtest,
)
from evemarket.store.quality import run_quality_checks
from evemarket.store.readers import (
    read_haul_quotes,
    read_price_series,
    read_station_quotes,
)
from evemarket.store.schema import ensure_market_db

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


@app.command("ingest-prices")
def ingest_prices_command(
    config: Path = typer.Option(
        Path("config.toml"),
        "--config",
        "-c",
        help="Path to a TOML configuration file.",
    ),
) -> None:
    """Fetch and store global ESI market prices."""

    loaded_config = load_config(config)
    result = asyncio.run(_run_ingest_prices(loaded_config))

    typer.echo(f"Status: {result.status}")
    typer.echo(f"Run ID: {result.run_id}")
    typer.echo(f"Price count: {result.price_count}")
    typer.echo(f"ESI expires: {result.esi_expires}")
    typer.echo(f"Snapshot ts: {result.snapshot_ts}")


async def _run_ingest_prices(config):
    async with ESIClient(config=config) as client:
        return await ingest_prices(client, config)


@app.command("scan")
def scan_command(
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
    station: int | None = typer.Option(
        None,
        "--station",
        help="EVE station ID. Defaults to the configured home hub station.",
    ),
    min_roi: float = typer.Option(
        0.0,
        "--min-roi",
        help="Minimum ROI fraction.",
    ),
    min_unit_profit: float = typer.Option(
        0.0,
        "--min-unit-profit",
        help="Minimum net ISK profit per unit.",
    ),
    min_daily_volume: float = typer.Option(
        0.0,
        "--min-daily-volume",
        help="Minimum average daily traded volume.",
    ),
    limit: int = typer.Option(
        20,
        "--limit",
        min=1,
        help="Maximum number of opportunities to print.",
    ),
    volume_window_days: int = typer.Option(
        30,
        "--volume-window-days",
        min=1,
        help="Trailing market-history window for average daily volume.",
    ),
) -> None:
    """Scan latest station-trade opportunities."""

    loaded_config = load_config(config)
    selected_region = region or loaded_config.tracked_regions[0]
    selected_station = (
        station if station is not None else loaded_config.home_hub_station_id
    )
    quotes = read_station_quotes(
        loaded_config,
        selected_region,
        selected_station,
        volume_window_days=volume_window_days,
    )
    results = scan_station_trades(
        quotes,
        loaded_config,
        min_roi=min_roi,
        min_unit_profit=min_unit_profit,
        min_daily_volume=min_daily_volume,
        limit=limit,
    )

    typer.echo(
        f"Region: {selected_region}  Station: {selected_station}  Quotes: {len(quotes)}"
    )
    if not quotes:
        typer.echo(
            f"No market snapshot found for region {selected_region}. "
            "Run ingest-orders first."
        )
        return
    if not results:
        typer.echo("No station-trade opportunities met the filters.")
        return

    typer.echo(_format_scan_table(results))


def _format_scan_table(results: list[StationTradeResult]) -> str:
    rows = [
        (
            str(result.type_id),
            result.type_name,
            f"{result.buy_price:,.2f}",
            f"{result.sell_price:,.2f}",
            f"{result.spread:,.2f}",
            f"{result.unit_profit:,.2f}",
            f"{result.roi * 100:,.2f}",
            f"{result.daily_volume:,.2f}",
        )
        for result in results
    ]
    headers = (
        "type_id",
        "type_name",
        "buy",
        "sell",
        "spread",
        "unit_profit",
        "roi%",
        "daily_vol",
    )
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]
    lines = [
        (
            f"{headers[0]:>{widths[0]}}  {headers[1]:<{widths[1]}}  "
            f"{headers[2]:>{widths[2]}}  {headers[3]:>{widths[3]}}  "
            f"{headers[4]:>{widths[4]}}  {headers[5]:>{widths[5]}}  "
            f"{headers[6]:>{widths[6]}}  {headers[7]:>{widths[7]}}"
        )
    ]
    for row in rows:
        lines.append(
            (
                f"{row[0]:>{widths[0]}}  {row[1]:<{widths[1]}}  "
                f"{row[2]:>{widths[2]}}  {row[3]:>{widths[3]}}  "
                f"{row[4]:>{widths[4]}}  {row[5]:>{widths[5]}}  "
                f"{row[6]:>{widths[6]}}  {row[7]:>{widths[7]}}"
            )
        )
    return "\n".join(lines)


@app.command("haul")
def haul_command(
    config: Path = typer.Option(
        Path("config.toml"),
        "--config",
        "-c",
        help="Path to a TOML configuration file.",
    ),
    source_region: int | None = typer.Option(
        None,
        "--source-region",
        help="Source EVE region ID. Defaults to the first configured tracked region.",
    ),
    source_station: int | None = typer.Option(
        None,
        "--source-station",
        help="Source EVE station ID. Defaults to the configured home hub station.",
    ),
    dest_region: int | None = typer.Option(
        None,
        "--dest-region",
        help="Destination EVE region ID.",
    ),
    dest_station: int | None = typer.Option(
        None,
        "--dest-station",
        help="Destination EVE station ID.",
    ),
    min_roi: float = typer.Option(
        0.0,
        "--min-roi",
        help="Minimum ROI fraction.",
    ),
    min_total_profit: float = typer.Option(
        0.0,
        "--min-total-profit",
        help="Minimum net ISK total profit.",
    ),
    min_daily_volume: float = typer.Option(
        0.0,
        "--min-daily-volume",
        help="Minimum destination average daily traded volume.",
    ),
    max_days_to_sell: float | None = typer.Option(
        None,
        "--max-days-to-sell",
        help="Maximum estimated days to sell at destination volume.",
    ),
    limit: int = typer.Option(
        20,
        "--limit",
        min=1,
        help="Maximum number of opportunities to print.",
    ),
    volume_window_days: int = typer.Option(
        30,
        "--volume-window-days",
        min=1,
        help="Trailing market-history window for average daily volume.",
    ),
) -> None:
    """Scan latest cross-region hauling opportunities."""

    loaded_config = load_config(config)
    selected_source_region = source_region or loaded_config.tracked_regions[0]
    selected_source_station = (
        source_station
        if source_station is not None
        else loaded_config.home_hub_station_id
    )
    if dest_region is None or dest_station is None:
        raise typer.BadParameter("--dest-region and --dest-station are required.")

    quotes = read_haul_quotes(
        loaded_config,
        selected_source_region,
        selected_source_station,
        dest_region,
        dest_station,
        volume_window_days=volume_window_days,
    )
    results = scan_haul_opportunities(
        quotes,
        loaded_config,
        min_roi=min_roi,
        min_total_profit=min_total_profit,
        min_daily_volume=min_daily_volume,
        max_days_to_sell=max_days_to_sell,
        limit=limit,
    )

    typer.echo(
        f"Source: {selected_source_region}/{selected_source_station}  "
        f"Dest: {dest_region}/{dest_station}  Quotes: {len(quotes)}"
    )
    if not quotes:
        typer.echo(
            "No market snapshot found for the source/destination regions. "
            "Run ingest-orders for both first."
        )
        return
    if not results:
        typer.echo("No haul opportunities met the filters.")
        return

    typer.echo(_format_haul_table(results))


def _format_haul_table(results: list[HaulResult]) -> str:
    rows = [
        (
            str(result.type_id),
            result.type_name,
            f"{result.source_price:,.2f}",
            f"{result.dest_price:,.2f}",
            str(result.quantity),
            f"{result.total_volume_m3:,.2f}",
            f"{result.unit_profit:,.2f}",
            f"{result.total_profit:,.2f}",
            f"{result.roi * 100:,.2f}",
            f"{result.profit_per_m3:,.2f}",
            f"{result.daily_volume:,.2f}",
            f"{result.days_to_sell:,.2f}",
        )
        for result in results
    ]
    headers = (
        "type_id",
        "type_name",
        "source",
        "dest",
        "qty",
        "total_m3",
        "unit_profit",
        "total_profit",
        "roi%",
        "profit/m3",
        "daily_vol",
        "days_to_sell",
    )
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]
    lines = [
        (
            f"{headers[0]:>{widths[0]}}  {headers[1]:<{widths[1]}}  "
            f"{headers[2]:>{widths[2]}}  {headers[3]:>{widths[3]}}  "
            f"{headers[4]:>{widths[4]}}  {headers[5]:>{widths[5]}}  "
            f"{headers[6]:>{widths[6]}}  {headers[7]:>{widths[7]}}  "
            f"{headers[8]:>{widths[8]}}  {headers[9]:>{widths[9]}}  "
            f"{headers[10]:>{widths[10]}}  {headers[11]:>{widths[11]}}"
        )
    ]
    for row in rows:
        lines.append(
            (
                f"{row[0]:>{widths[0]}}  {row[1]:<{widths[1]}}  "
                f"{row[2]:>{widths[2]}}  {row[3]:>{widths[3]}}  "
                f"{row[4]:>{widths[4]}}  {row[5]:>{widths[5]}}  "
                f"{row[6]:>{widths[6]}}  {row[7]:>{widths[7]}}  "
                f"{row[8]:>{widths[8]}}  {row[9]:>{widths[9]}}  "
                f"{row[10]:>{widths[10]}}  {row[11]:>{widths[11]}}"
            )
        )
    return "\n".join(lines)


@app.command("backtest")
def backtest_command(
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
    type: int = typer.Option(
        34,
        "--type",
        min=1,
        help="EVE type ID to backtest.",
    ),
    horizon: int = typer.Option(
        7,
        "--horizon",
        min=1,
        help="Forecast/hold horizon in days.",
    ),
    warmup: int = typer.Option(
        30,
        "--warmup",
        min=1,
        help="Minimum history before the first decision.",
    ),
    season_length: int = typer.Option(
        7,
        "--season-length",
        min=1,
        help="Seasonal-naive period.",
    ),
) -> None:
    """Backtest baseline long-hold strategies against price history."""

    loaded_config = load_config(config)
    selected_region = region or loaded_config.tracked_regions[0]
    if season_length > warmup:
        raise typer.BadParameter(
            "--warmup must be >= --season-length so the seasonal baseline "
            "always has a full prior season."
        )

    series = read_price_series(loaded_config, selected_region, type)
    typer.echo(
        f"Region: {selected_region}  Type: {type}  Points: {len(series)}  "
        f"Horizon: {horizon}  Warmup: {warmup}  Season: {season_length}"
    )
    if not series:
        typer.echo(
            f"No price history found for region {selected_region} type {type}. "
            "Run ingest-history or backfill-history first."
        )
        return

    def _seasonal(series: Sequence[PricePoint], *, horizon: int) -> Forecast:
        return seasonal_naive_forecast(
            series,
            horizon=horizon,
            season_length=season_length,
        )

    naive = run_forecaster_backtest(
        series,
        naive_persistence_forecast,
        loaded_config,
        horizon=horizon,
        warmup=warmup,
    )
    seasonal = run_forecaster_backtest(
        series,
        _seasonal,
        loaded_config,
        horizon=horizon,
        warmup=warmup,
    )
    buy_hold = buy_and_hold_outcomes(series, loaded_config)
    rows = [
        ("naive-persistence", compute_metrics(naive)),
        ("seasonal-naive", compute_metrics(seasonal)),
        ("buy-and-hold", compute_metrics(buy_hold)),
    ]

    typer.echo(_format_backtest_table(rows))
    typer.echo(
        "Reference: hold-ISK (do nothing) = 0.00 ISK/trade expectancy "
        "(the abstention floor)."
    )
    clearing = [
        label for label, metrics in rows if metrics.sample_size > 0 and metrics.expectancy > 0
    ]
    typer.echo(
        "Baselines clearing the floor (expectancy > 0): "
        + (", ".join(clearing) if clearing else "none")
    )


def _format_backtest_table(rows: list[tuple[str, BacktestMetrics]]) -> str:
    table_rows = [
        (
            label,
            str(metrics.sample_size),
            f"{metrics.hit_rate * 100:,.2f}",
            f"{metrics.expectancy:,.2f}",
            f"{metrics.profit_factor:,.2f}",
            f"{metrics.max_drawdown:,.2f}",
            f"{metrics.total_net_isk:,.2f}",
            f"{metrics.expectancy_t_stat:,.2f}",
        )
        for label, metrics in rows
    ]
    headers = (
        "strategy",
        "sample",
        "hit%",
        "expectancy",
        "profit_factor",
        "max_dd",
        "total",
        "t_stat",
    )
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in table_rows))
        for index in range(len(headers))
    ]
    lines = [
        (
            f"{headers[0]:<{widths[0]}}  {headers[1]:>{widths[1]}}  "
            f"{headers[2]:>{widths[2]}}  {headers[3]:>{widths[3]}}  "
            f"{headers[4]:>{widths[4]}}  {headers[5]:>{widths[5]}}  "
            f"{headers[6]:>{widths[6]}}  {headers[7]:>{widths[7]}}"
        )
    ]
    for row in table_rows:
        lines.append(
            (
                f"{row[0]:<{widths[0]}}  {row[1]:>{widths[1]}}  "
                f"{row[2]:>{widths[2]}}  {row[3]:>{widths[3]}}  "
                f"{row[4]:>{widths[4]}}  {row[5]:>{widths[5]}}  "
                f"{row[6]:>{widths[6]}}  {row[7]:>{widths[7]}}"
            )
        )
    return "\n".join(lines)


@app.command("schedule")
def schedule_command(
    config: Path = typer.Option(
        Path("config.toml"),
        "--config",
        "-c",
        help="Path to a TOML configuration file.",
    ),
    orders_interval: int = typer.Option(
        5,
        "--orders-interval",
        help="Orders snapshot interval, minutes",
    ),
    prices_interval: int = typer.Option(
        60,
        "--prices-interval",
        help="Prices snapshot interval, minutes",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="List jobs without starting the scheduler.",
    ),
) -> None:
    """Start recurring ingest jobs."""

    loaded_config = load_config(config)
    sched = build_scheduler(
        loaded_config,
        orders_interval_minutes=orders_interval,
        prices_interval_minutes=prices_interval,
    )

    for job in sched.get_jobs():
        typer.echo(f"Job {job.id}: {job.trigger}")

    if dry_run:
        typer.echo("Dry run: scheduler not started.")
        return

    typer.echo("Starting scheduler. Ctrl+C to stop.")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        sched.shutdown()


@app.command("quality-check")
def quality_check_command(
    config: Path = typer.Option(
        Path("config.toml"),
        "--config",
        "-c",
        help="Path to a TOML configuration file.",
    ),
    max_price_age_hours: float = typer.Option(
        24.0,
        "--max-price-age-hours",
        help="Maximum latest price snapshot age, hours.",
    ),
    max_history_age_days: int = typer.Option(
        3,
        "--max-history-age-days",
        help="Maximum latest history row age, days.",
    ),
) -> None:
    """Run read-only market data quality checks."""

    loaded_config = load_config(config)
    market_db = loaded_config.data_dir.expanduser() / "market.duckdb"
    with ensure_market_db(market_db) as conn:
        checks = run_quality_checks(
            conn,
            max_price_age_hours=max_price_age_hours,
            max_history_age_days=max_history_age_days,
        )

    for check in checks:
        typer.echo(f"[{check.status.upper()}] {check.name}: {check.detail}")

    if any(check.status == "fail" for check in checks):
        raise typer.Exit(code=1)
