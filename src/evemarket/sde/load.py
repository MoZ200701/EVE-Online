"""Download and load Fuzzwork SDE reference tables."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import httpx

FUZZWORK_CSV_BASE_URL = "https://www.fuzzwork.co.uk/dump/latest/csv"
DEFAULT_USER_AGENT = "eve-market-tool/0.1 (contact: REPLACE_ME)"


@dataclass(frozen=True)
class TableSpec:
    """Mapping from a Fuzzwork CSV to a local DuckDB table."""

    source_name: str
    table_name: str
    primary_key: str
    columns: tuple[tuple[str, str], ...]


TABLE_SPECS: tuple[TableSpec, ...] = (
    TableSpec(
        source_name="invTypes",
        table_name="sde_types",
        primary_key="type_id",
        columns=(
            ("typeID", "type_id"),
            ("typeName", "type_name"),
            ("groupID", "group_id"),
            ("marketGroupID", "market_group_id"),
            ("volume", "volume"),
            ("published", "published"),
        ),
    ),
    TableSpec(
        source_name="mapRegions",
        table_name="sde_regions",
        primary_key="region_id",
        columns=(
            ("regionID", "region_id"),
            ("regionName", "region_name"),
        ),
    ),
    TableSpec(
        source_name="staStations",
        table_name="sde_stations",
        primary_key="station_id",
        columns=(
            ("stationID", "station_id"),
            ("stationName", "station_name"),
            ("regionID", "region_id"),
            ("solarSystemID", "solar_system_id"),
        ),
    ),
    TableSpec(
        source_name="invMarketGroups",
        table_name="sde_market_groups",
        primary_key="market_group_id",
        columns=(
            ("marketGroupID", "market_group_id"),
            ("parentGroupID", "parent_group_id"),
            ("marketGroupName", "market_group_name"),
        ),
    ),
    TableSpec(
        source_name="mapSolarSystems",
        table_name="sde_solar_systems",
        primary_key="solar_system_id",
        columns=(
            ("solarSystemID", "solar_system_id"),
            ("regionID", "region_id"),
            ("security", "security_status"),
        ),
    ),
)


def download_sde(
    cache_dir: Path,
    user_agent: str = DEFAULT_USER_AGENT,
) -> dict[str, Path]:
    """Download required Fuzzwork CSV files into a local cache directory."""

    cache_dir.mkdir(parents=True, exist_ok=True)
    csv_files: dict[str, Path] = {}
    headers = {"User-Agent": user_agent}

    with httpx.Client(follow_redirects=True, timeout=60.0, headers=headers) as client:
        for spec in TABLE_SPECS:
            filename = f"{spec.source_name}.csv"
            csv_path = cache_dir / filename
            csv_files[spec.source_name] = csv_path

            if csv_path.exists():
                continue

            url = f"{FUZZWORK_CSV_BASE_URL}/{filename}"
            with client.stream("GET", url) as response:
                response.raise_for_status()
                with csv_path.open("wb") as csv_file:
                    for chunk in response.iter_bytes():
                        csv_file.write(chunk)

    return csv_files


def connect(duckdb_path: Path) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection, creating parent directories as needed."""

    duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(duckdb_path))


def load_sde(duckdb_path: Path, csv_files: dict[str, Path]) -> None:
    """Load the selected SDE columns into DuckDB, replacing existing tables."""

    with connect(duckdb_path) as connection:
        for spec in TABLE_SPECS:
            csv_path = csv_files[spec.source_name]
            select_list = ", ".join(
                f'"{source}" AS {target}' for source, target in spec.columns
            )

            connection.execute(f"DROP TABLE IF EXISTS {spec.table_name}")
            connection.execute(
                f"""
                CREATE TABLE {spec.table_name} AS
                SELECT {select_list}
                FROM read_csv_auto(?, header = true)
                """,
                [str(csv_path)],
            )
            connection.execute(
                f"ALTER TABLE {spec.table_name} ADD PRIMARY KEY ({spec.primary_key})"
            )


def table_counts(connection: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Return row counts for all loaded SDE tables."""

    return {
        spec.table_name: connection.execute(
            f"SELECT count(*) FROM {spec.table_name}"
        ).fetchone()[0]
        for spec in TABLE_SPECS
    }
