from pathlib import Path

from evemarket.sde.load import TABLE_SPECS, connect, load_sde, table_counts


def fixture_csv_files() -> dict[str, Path]:
    fixture_dir = Path(__file__).parent / "fixtures" / "sde"
    return {
        spec.source_name: fixture_dir / f"{spec.source_name}.csv"
        for spec in TABLE_SPECS
    }


def test_load_sde_creates_tables_and_is_idempotent(tmp_path: Path) -> None:
    duckdb_path = tmp_path / "sde.duckdb"
    csv_files = fixture_csv_files()

    load_sde(duckdb_path, csv_files)

    with connect(duckdb_path) as connection:
        counts = table_counts(connection)
        tritanium = connection.execute(
            "SELECT type_name FROM sde_types WHERE type_id = 34"
        ).fetchone()
        the_forge = connection.execute(
            "SELECT region_name FROM sde_regions WHERE region_id = 10000002"
        ).fetchone()

    assert counts == {
        "sde_types": 3,
        "sde_regions": 2,
        "sde_stations": 2,
        "sde_market_groups": 2,
        "sde_solar_systems": 2,
    }
    assert tritanium == ("Tritanium",)
    assert the_forge == ("The Forge",)

    load_sde(duckdb_path, csv_files)

    with connect(duckdb_path) as connection:
        assert table_counts(connection) == counts
