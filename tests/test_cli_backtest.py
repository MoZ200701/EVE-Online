from datetime import date, timedelta
from pathlib import Path

from typer.testing import CliRunner

from evemarket.cli import app
from evemarket.store.schema import ensure_market_db

REGION_ID = 10000002
ALT_REGION_ID = 10000043
TYPE_ID = 34
ALT_TYPE_ID = 35


def test_backtest_command_no_history_message(tmp_path: Path) -> None:
    _write_config(tmp_path)
    with ensure_market_db(tmp_path / "market.duckdb"):
        pass

    result = CliRunner().invoke(
        app,
        [
            "backtest",
            "--config",
            str(tmp_path / "config.toml"),
            "--warmup",
            "5",
            "--season-length",
            "5",
        ],
    )

    assert result.exit_code == 0
    assert "Points: 0" in result.output
    assert (
        "No price history found for region 10000002 type 34. "
        "Run ingest-history or backfill-history first."
    ) in result.output


def test_backtest_command_prints_baseline_report(tmp_path: Path) -> None:
    _write_config(tmp_path)
    _write_history(tmp_path, REGION_ID, TYPE_ID, 40)

    result = CliRunner().invoke(
        app,
        [
            "backtest",
            "--config",
            str(tmp_path / "config.toml"),
            "--warmup",
            "5",
            "--season-length",
            "5",
            "--horizon",
            "1",
        ],
    )

    assert result.exit_code == 0
    assert "Region: 10000002  Type: 34  Points: 40" in result.output
    assert "strategy" in result.output
    assert "naive-persistence" in result.output
    assert "seasonal-naive" in result.output
    assert "buy-and-hold" in result.output
    assert "Reference: hold-ISK" in result.output
    assert (
        "Baselines clearing the floor (expectancy > 0): buy-and-hold"
        in result.output
    )


def test_backtest_command_naive_persistence_abstains(tmp_path: Path) -> None:
    _write_config(tmp_path)
    _write_history(tmp_path, REGION_ID, TYPE_ID, 40)

    result = CliRunner().invoke(
        app,
        [
            "backtest",
            "--config",
            str(tmp_path / "config.toml"),
            "--warmup",
            "5",
            "--season-length",
            "5",
            "--horizon",
            "1",
        ],
    )

    assert result.exit_code == 0
    naive_row = next(
        line for line in result.output.splitlines() if line.startswith("naive-persistence")
    )
    clearing_line = next(
        line
        for line in result.output.splitlines()
        if line.startswith("Baselines clearing")
    )
    assert naive_row.split()[1] == "0"
    assert "naive-persistence" not in clearing_line


def test_backtest_command_rejects_warmup_shorter_than_season_length(
    tmp_path: Path,
) -> None:
    _write_config(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "backtest",
            "--config",
            str(tmp_path / "config.toml"),
            "--warmup",
            "3",
            "--season-length",
            "7",
        ],
    )

    assert result.exit_code == 2


def test_backtest_command_uses_region_and_type_options(tmp_path: Path) -> None:
    _write_config(tmp_path)
    _write_history(tmp_path, ALT_REGION_ID, ALT_TYPE_ID, 12)

    result = CliRunner().invoke(
        app,
        [
            "backtest",
            "--config",
            str(tmp_path / "config.toml"),
            "--region",
            str(ALT_REGION_ID),
            "--type",
            str(ALT_TYPE_ID),
            "--warmup",
            "5",
            "--season-length",
            "5",
            "--horizon",
            "1",
        ],
    )

    assert result.exit_code == 0
    assert "Region: 10000043  Type: 35  Points: 12" in result.output


def _write_config(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text(
        f'data_dir = "{tmp_path.as_posix()}"\n',
        encoding="utf-8",
    )


def _write_history(
    data_dir: Path,
    region_id: int,
    type_id: int,
    days: int,
) -> None:
    start = date(2026, 1, 1)
    rows = [
        (
            region_id,
            type_id,
            start + timedelta(days=offset),
            100.0 + offset * 5.0,
            101.0 + offset * 5.0,
            99.0 + offset * 5.0,
            10,
            1000,
        )
        for offset in range(days)
    ]
    with ensure_market_db(data_dir / "market.duckdb") as connection:
        connection.executemany(
            """
            INSERT INTO market_history (
                region_id, type_id, date, average, highest, lowest, order_count, volume
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
