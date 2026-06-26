"""Configuration loading for EVE Market Tool."""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

LOGGER = logging.getLogger(__name__)


class SkillConfig(BaseSettings):
    """Trade skill levels used by later fee calculations."""

    accounting: int = Field(default=0, ge=0, le=5)
    broker_relations: int = Field(default=0, ge=0, le=5)

    model_config = SettingsConfigDict(extra="forbid")


class Config(BaseSettings):
    """Application configuration."""

    user_agent: str = "eve-market-tool/0.1 (contact: REPLACE_ME)"
    tracked_regions: list[int] = Field(default_factory=lambda: [10000002])
    home_hub_station_id: int = 60003760
    data_dir: Path = Path("./data")
    skills: SkillConfig = Field(default_factory=SkillConfig)
    standings_factional: float = 0.0
    standings_corp: float = 0.0
    capital_isk: int = 1_000_000_000
    cargo_m3: float = 5000.0

    model_config = SettingsConfigDict(extra="forbid")


def load_config(path: str | Path = "config.toml") -> Config:
    """Load configuration from TOML, falling back to defaults if missing."""

    config_path = Path(path)
    if not config_path.exists():
        LOGGER.warning("Config file %s not found; using defaults.", config_path)
        return Config()

    with config_path.open("rb") as config_file:
        data: dict[str, Any] = tomllib.load(config_file)

    return Config.model_validate(data)

