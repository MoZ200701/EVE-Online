"""Streamlit dashboard for EVE Market Tool."""

from __future__ import annotations

from dataclasses import asdict

import streamlit as st

from evemarket.analytics.haul import HaulResult, scan_haul_opportunities
from evemarket.analytics.station_trade import StationTradeResult, scan_station_trades
from evemarket.config import load_config
from evemarket.store.readers import read_haul_quotes, read_station_quotes


def _result_rows(
    results: list[StationTradeResult] | list[HaulResult],
) -> list[dict[str, object]]:
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
dest_region = st.sidebar.number_input(
    "Dest region ID",
    value=0,
    step=1,
    key="dest_region",
)
dest_station = st.sidebar.number_input(
    "Dest station ID",
    value=0,
    step=1,
    key="dest_station",
)
min_total_profit = st.sidebar.number_input(
    "Minimum total profit",
    value=0.0,
    key="min_total_profit",
)
max_days_to_sell = st.sidebar.number_input(
    "Max days to sell (0 = no limit)",
    value=0.0,
    key="max_days_to_sell",
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

st.header("Hauling")

selected_dest_region = int(dest_region)
selected_dest_station = int(dest_station)
if selected_dest_region <= 0 or selected_dest_station <= 0:
    st.info("Enter a destination region and station to scan hauls.")
else:
    selected_max_days_to_sell = max_days_to_sell if max_days_to_sell > 0 else None
    haul_quotes = read_haul_quotes(
        loaded_config,
        selected_region,
        selected_station,
        selected_dest_region,
        selected_dest_station,
        volume_window_days=selected_volume_window_days,
    )
    haul_results = scan_haul_opportunities(
        haul_quotes,
        loaded_config,
        min_roi=min_roi,
        min_total_profit=min_total_profit,
        min_daily_volume=min_daily_volume,
        max_days_to_sell=selected_max_days_to_sell,
        limit=selected_limit,
    )

    st.caption(
        f"Source: {selected_region}/{selected_station}  "
        f"Dest: {selected_dest_region}/{selected_dest_station}  "
        f"Quotes: {len(haul_quotes)}"
    )
    if not haul_quotes:
        st.info(
            "No market snapshot found for the source/destination regions. "
            "Run ingest-orders for both first."
        )
    elif not haul_results:
        st.info("No haul opportunities met the filters.")
    else:
        st.dataframe(_result_rows(haul_results), use_container_width=True)
