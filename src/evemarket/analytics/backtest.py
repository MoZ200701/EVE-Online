"""Pure backtest metric primitives."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil, sqrt
from statistics import mean, stdev


@dataclass(frozen=True)
class TradeOutcome:
    """One realized backtest trade."""

    net_isk: float
    correct_direction: bool


@dataclass(frozen=True)
class BacktestMetrics:
    """Backtest scorecard."""

    sample_size: int
    hit_rate: float
    expectancy: float
    profit_factor: float
    max_drawdown: float
    total_net_isk: float
    expectancy_t_stat: float


def directional_hit_rate(outcomes: Sequence[TradeOutcome]) -> float:
    """Return the share of trades whose predicted direction was correct."""
    _require_outcomes(outcomes)
    hits = sum(1 for outcome in outcomes if outcome.correct_direction)
    return hits / len(outcomes)


def expectancy_per_trade(outcomes: Sequence[TradeOutcome]) -> float:
    """Return mean net ISK per trade."""
    _require_outcomes(outcomes)
    return mean(outcome.net_isk for outcome in outcomes)


def profit_factor(outcomes: Sequence[TradeOutcome]) -> float:
    """Return gross profit divided by gross loss magnitude."""
    _require_outcomes(outcomes)
    gross_profit = sum(outcome.net_isk for outcome in outcomes if outcome.net_isk > 0)
    gross_loss = sum(outcome.net_isk for outcome in outcomes if outcome.net_isk < 0)
    if gross_loss == 0:
        return float("inf")
    return gross_profit / abs(gross_loss)


def max_drawdown(outcomes: Sequence[TradeOutcome]) -> float:
    """Return worst cumulative ISK peak-to-trough drawdown."""
    _require_outcomes(outcomes)
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for outcome in outcomes:
        equity += outcome.net_isk
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def total_net_isk(outcomes: Sequence[TradeOutcome]) -> float:
    """Return total realized net ISK."""
    _require_outcomes(outcomes)
    return sum(outcome.net_isk for outcome in outcomes)


def expectancy_t_stat(outcomes: Sequence[TradeOutcome]) -> float:
    """Return one-sample t-statistic for net ISK versus zero."""
    _require_outcomes(outcomes)
    if len(outcomes) < 2:
        return 0.0

    values = [outcome.net_isk for outcome in outcomes]
    sample_stdev = stdev(values)
    if sample_stdev == 0:
        return 0.0

    return mean(values) / (sample_stdev / sqrt(len(values)))


def compute_metrics(outcomes: Sequence[TradeOutcome]) -> BacktestMetrics:
    """Aggregate realized trade outcomes into a backtest scorecard."""
    if not outcomes:
        return BacktestMetrics(
            sample_size=0,
            hit_rate=float("nan"),
            expectancy=float("nan"),
            profit_factor=float("nan"),
            max_drawdown=0.0,
            total_net_isk=0.0,
            expectancy_t_stat=float("nan"),
        )

    return BacktestMetrics(
        sample_size=len(outcomes),
        hit_rate=directional_hit_rate(outcomes),
        expectancy=expectancy_per_trade(outcomes),
        profit_factor=profit_factor(outcomes),
        max_drawdown=max_drawdown(outcomes),
        total_net_isk=total_net_isk(outcomes),
        expectancy_t_stat=expectancy_t_stat(outcomes),
    )


def _require_outcomes(outcomes: Sequence[TradeOutcome]) -> None:
    if not outcomes:
        raise ValueError("outcomes must not be empty")


@dataclass(frozen=True)
class PricePoint:
    """One point in a point-in-time daily price series."""

    date: str
    price: float


@dataclass(frozen=True)
class Forecast:
    """One forecaster prediction for a future point."""

    predicted_price: float
    direction: int


def naive_persistence_forecast(
    series: Sequence[PricePoint],
    *,
    horizon: int,
) -> Forecast:
    """Predict the last observed price at the target horizon."""
    _require_price_series(series)
    if horizon < 1:
        raise ValueError("horizon must be at least 1")

    return Forecast(predicted_price=series[-1].price, direction=0)


def seasonal_naive_forecast(
    series: Sequence[PricePoint],
    *,
    horizon: int,
    season_length: int,
) -> Forecast:
    """Predict from the matching point in the prior season."""
    _require_price_series(series)
    if horizon < 1:
        raise ValueError("horizon must be at least 1")
    if season_length < 1:
        raise ValueError("season_length must be at least 1")

    idx = (len(series) - 1) + horizon - season_length * ceil(horizon / season_length)
    if idx < 0:
        raise ValueError("series too short for seasonal_naive at this horizon/season_length")

    predicted_price = series[idx].price
    return Forecast(
        predicted_price=predicted_price,
        direction=_sign(predicted_price - series[-1].price),
    )


def _require_price_series(series: Sequence[PricePoint]) -> None:
    if not series:
        raise ValueError("series must not be empty")


def _sign(delta: float) -> int:
    if delta > 0:
        return 1
    if delta < 0:
        return -1
    return 0
