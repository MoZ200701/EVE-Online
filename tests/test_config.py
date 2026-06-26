from pathlib import Path

from typer.testing import CliRunner

from evemarket.cli import app
from evemarket.config import load_config


def test_defaults_load_when_no_file(tmp_path: Path) -> None:
    config = load_config(tmp_path / "missing.toml")

    assert config.user_agent == "eve-market-tool/0.1 (contact: REPLACE_ME)"
    assert config.tracked_regions == [10000002]
    assert config.home_hub_station_id == 60003760
    assert config.data_dir == Path("./data")
    assert config.skills.accounting == 0
    assert config.skills.broker_relations == 0
    assert config.standings_factional == 0.0
    assert config.standings_corp == 0.0
    assert config.capital_isk == 1_000_000_000
    assert config.cargo_m3 == 5000.0


def test_temp_config_overrides_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
user_agent = "eve-market-tool/0.1 (contact: pilot@example.com)"
tracked_regions = [10000002, 10000043]
home_hub_station_id = 60008494
data_dir = "./custom-data"
standings_factional = 1.5
standings_corp = 2.25
capital_isk = 2500000000
cargo_m3 = 12500.5

[skills]
accounting = 4
broker_relations = 3
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.user_agent == "eve-market-tool/0.1 (contact: pilot@example.com)"
    assert config.tracked_regions == [10000002, 10000043]
    assert config.home_hub_station_id == 60008494
    assert config.data_dir == Path("./custom-data")
    assert config.skills.accounting == 4
    assert config.skills.broker_relations == 3
    assert config.standings_factional == 1.5
    assert config.standings_corp == 2.25
    assert config.capital_isk == 2_500_000_000
    assert config.cargo_m3 == 12500.5


def test_info_command_exits_zero(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
user_agent = "eve-market-tool/0.1 (contact: pilot@example.com)"
data_dir = "./data"
""".strip(),
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(app, ["info", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "Data dir:" in result.stdout
    assert "Tracked regions:" in result.stdout
    assert "User-Agent set: yes" in result.stdout


def test_info_command_warns_on_placeholder_user_agent(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["info", "--config", str(tmp_path / "missing.toml")])

    assert result.exit_code == 0
    assert "WARNING: User-Agent still contains REPLACE_ME" in result.stdout
