"""Streamlit dashboard for EVE Market Tool."""

from __future__ import annotations

from dataclasses import asdict

import streamlit as st

from evemarket.analytics.station_trade import StationTradeResult, scan_station_trades
from evemarket.config import load_config
from evemarket.store.readers import read_station_quotes


def _result_rows(results: list[StationTradeResult]) -> list[dict[str, object]]:
    return [asdict(result) for result in results]


st.title("EVE Market Tool")

config_path = st.sidebar.text_input(
    "Config file",
    value="config.toml",
    key="config_path",
)
loaded_config = load_config(config_path)

region = st.sidebar.number_input(
    "Region ID",
    value=loaded_config.tracked_regions[0],
    step=1,
    key="region",
)
station = st.sidebar.number_input(
    "Station ID",
    value=loaded_config.home_hub_station_id,
    step=1,
    key="station",
)
min_roi = st.sidebar.number_input(
    "Minimum ROI",
    value=0.0,
    key="min_roi",
)
min_unit_profit = st.sidebar.number_input(
    "Minimum unit profit",
    value=0.0,
    key="min_unit_profit",
)
min_daily_volume = st.sidebar.number_input(
    "Minimum daily volume",
    value=0.0,
    key="min_daily_volume",
)
limit = st.sidebar.number_input(
    "Limit",
    value=20,
    min_value=1,
    step=1,
    key="limit",
)
volume_window_days = st.sidebar.number_input(
    "Volume window (days)",
    value=30,
    min_value=1,
    step=1,
    key="volume_window_days",
)

selected_region = int(region)
selected_station = int(station)
selected_limit = int(limit)
selected_volume_window_days = int(volume_window_days)

st.header("Station Trading")

quotes = read_station_quotes(
    loaded_config,
    selected_region,
    selected_station,
    volume_window_days=selected_volume_window_days,
)
results = scan_station_trades(
    quotes,
    loaded_config,
    min_roi=min_roi,
    min_unit_profit=min_unit_profit,
    min_daily_volume=min_daily_volume,
    limit=selected_limit,
)

st.caption(
    f"Region: {selected_region}  Station: {selected_station}  Quotes: {len(quotes)}"
)
if not quotes:
    st.info(f"No market snapshot found for region {selected_region}. Run ingest-orders first.")
elif not results:
    st.info("No station-trade opportunities met the filters.")
else:
    st.dataframe(_result_rows(results), use_container_width=True)
