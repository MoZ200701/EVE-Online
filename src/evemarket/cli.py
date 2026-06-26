"""Command-line interface for EVE Market Tool."""

from __future__ import annotations

from pathlib import Path

import typer

from evemarket.config import load_config
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
