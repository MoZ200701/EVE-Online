"""Pure station-trade ranking core."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from evemarket.analytics.opportunity import station_trade_opportunity
from evemarket.config import Config


@dataclass(frozen=True)
class MarketQuote:
    """One item's in-station two-sided market."""

    type_id: int
    type_name: str
    best_bid: float
    best_ask: float
    daily_volume: float


@dataclass(frozen=True)
class StationTradeResult:
    """Ranked station-trade suggestion."""

    type_id: int
    type_name: str
    buy_price: float
    sell_price: float
    spread: float
    unit_profit: float
    roi: float
    daily_volume: float


def scan_station_trades(
    quotes: Iterable[MarketQuote],
    config: Config,
    *,
    min_roi: float = 0.0,
    min_unit_profit: float = 0.0,
    min_daily_volume: float = 0.0,
    limit: int | None = None,
) -> list[StationTradeResult]:
    """Rank station-trade opportunities from market quotes."""
    if min_roi < 0:
        raise ValueError("min_roi must be non-negative")
    if min_unit_profit < 0:
        raise ValueError("min_unit_profit must be non-negative")
    if min_daily_volume < 0:
        raise ValueError("min_daily_volume must be non-negative")
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1")

    results: list[StationTradeResult] = []
    for quote in quotes:
        if quote.best_bid <= 0 or quote.best_ask <= 0:
            continue

        opportunity = station_trade_opportunity(
            config,
            buy_price=quote.best_bid,
            sell_price=quote.best_ask,
            quantity=1,
        )
        unit_profit = opportunity.profit
        roi = opportunity.roi
        if (
            unit_profit < min_unit_profit
            or roi < min_roi
            or quote.daily_volume < min_daily_volume
        ):
            continue

        results.append(
            StationTradeResult(
                type_id=quote.type_id,
                type_name=quote.type_name,
                buy_price=quote.best_bid,
                sell_price=quote.best_ask,
                spread=quote.best_ask - quote.best_bid,
                unit_profit=unit_profit,
                roi=roi,
                daily_volume=quote.daily_volume,
            )
        )

    results.sort(key=lambda result: (-result.roi, -result.daily_volume, result.type_id))
    if limit is not None:
        return results[:limit]
    return results
