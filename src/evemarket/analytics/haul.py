"""Pure hauling opportunity ranking core."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from math import floor

from evemarket.analytics.opportunity import station_trade_opportunity
from evemarket.config import Config


@dataclass(frozen=True)
class HaulQuote:
    """One cross-region executable haul quote."""

    type_id: int
    type_name: str
    source_price: float
    dest_price: float
    volume_m3: float
    daily_volume: float


@dataclass(frozen=True)
class HaulResult:
    """Ranked hauling suggestion."""

    type_id: int
    type_name: str
    source_price: float
    dest_price: float
    quantity: int
    total_volume_m3: float
    unit_profit: float
    total_profit: float
    roi: float
    profit_per_m3: float
    daily_volume: float
    days_to_sell: float


def scan_haul_opportunities(
    quotes: Iterable[HaulQuote],
    config: Config,
    *,
    min_roi: float = 0.0,
    min_total_profit: float = 0.0,
    min_daily_volume: float = 0.0,
    max_days_to_sell: float | None = None,
    limit: int | None = None,
) -> list[HaulResult]:
    """Rank regional arbitrage opportunities from haul quotes."""
    if min_roi < 0:
        raise ValueError("min_roi must be non-negative")
    if min_total_profit < 0:
        raise ValueError("min_total_profit must be non-negative")
    if min_daily_volume < 0:
        raise ValueError("min_daily_volume must be non-negative")
    if max_days_to_sell is not None and max_days_to_sell <= 0:
        raise ValueError("max_days_to_sell must be positive")
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1")

    results: list[HaulResult] = []
    for quote in quotes:
        if quote.source_price <= 0 or quote.dest_price <= 0 or quote.volume_m3 <= 0:
            continue

        units_by_cargo = floor(config.cargo_m3 / quote.volume_m3)
        per_unit_cost = station_trade_opportunity(
            config,
            buy_price=quote.source_price,
            sell_price=quote.dest_price,
            quantity=1,
        ).cost
        units_by_capital = floor(config.capital_isk / per_unit_cost) if per_unit_cost > 0 else 0
        quantity = min(units_by_cargo, units_by_capital)
        if quantity < 1:
            continue

        opportunity = station_trade_opportunity(
            config,
            buy_price=quote.source_price,
            sell_price=quote.dest_price,
            quantity=quantity,
        )
        total_profit = opportunity.profit
        roi = opportunity.roi
        unit_profit = total_profit / quantity
        total_volume_m3 = quantity * quote.volume_m3
        profit_per_m3 = total_profit / total_volume_m3
        days_to_sell = quantity / quote.daily_volume if quote.daily_volume > 0 else float("inf")

        if (
            roi < min_roi
            or total_profit < min_total_profit
            or quote.daily_volume < min_daily_volume
            or (max_days_to_sell is not None and days_to_sell > max_days_to_sell)
        ):
            continue

        results.append(
            HaulResult(
                type_id=quote.type_id,
                type_name=quote.type_name,
                source_price=quote.source_price,
                dest_price=quote.dest_price,
                quantity=quantity,
                total_volume_m3=total_volume_m3,
                unit_profit=unit_profit,
                total_profit=total_profit,
                roi=roi,
                profit_per_m3=profit_per_m3,
                daily_volume=quote.daily_volume,
                days_to_sell=days_to_sell,
            )
        )

    results.sort(key=lambda result: (-result.total_profit, -result.roi, result.type_id))
    if limit is not None:
        return results[:limit]
    return results
