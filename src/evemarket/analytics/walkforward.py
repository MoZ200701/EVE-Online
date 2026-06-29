"""Walk-forward backtest engine."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from evemarket.analytics.backtest import Forecast, PricePoint, TradeOutcome
from evemarket.analytics.opportunity import station_trade_opportunity
from evemarket.config import Config


class Forecaster(Protocol):
    def __call__(self, series: Sequence[PricePoint], *, horizon: int) -> Forecast: ...


def run_forecaster_backtest(
    series: Sequence[PricePoint],
    forecaster: Forecaster,
    config: Config,
    *,
    horizon: int,
    warmup: int,
) -> list[TradeOutcome]:
    """Return fee-net trade outcomes from a point-in-time forecaster."""
    if horizon < 1:
        raise ValueError("horizon must be at least 1")
    if warmup < 1:
        raise ValueError("warmup must be at least 1")

    outcomes: list[TradeOutcome] = []
    for t in range(warmup - 1, len(series) - horizon):
        history = series[: t + 1]
        forecast = forecaster(history, horizon=horizon)
        buy_price = series[t].price
        predicted_profit = station_trade_opportunity(
            config,
            buy_price=buy_price,
            sell_price=forecast.predicted_price,
            quantity=1,
        ).profit
        if predicted_profit <= 0:
            continue

        realized_price = series[t + horizon].price
        net_isk = station_trade_opportunity(
            config,
            buy_price=buy_price,
            sell_price=realized_price,
            quantity=1,
        ).profit
        realized_delta = realized_price - buy_price
        realized_direction = (realized_delta > 0) - (realized_delta < 0)
        outcomes.append(
            TradeOutcome(
                net_isk=net_isk,
                correct_direction=realized_direction == forecast.direction,
            )
        )

    return outcomes


def buy_and_hold_outcomes(
    series: Sequence[PricePoint],
    config: Config,
) -> list[TradeOutcome]:
    """Return one fee-net buy-and-hold round trip."""
    if len(series) < 2:
        return []

    first_price = series[0].price
    last_price = series[-1].price
    opportunity = station_trade_opportunity(
        config,
        buy_price=first_price,
        sell_price=last_price,
        quantity=1,
    )
    return [
        TradeOutcome(
            net_isk=opportunity.profit,
            correct_direction=last_price > first_price,
        )
    ]
