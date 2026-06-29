import math
from collections.abc import Sequence

import pytest

from evemarket.analytics.backtest import (
    Forecast,
    PricePoint,
    compute_metrics,
    naive_persistence_forecast,
    seasonal_naive_forecast,
)
from evemarket.analytics.opportunity import station_trade_opportunity
from evemarket.analytics.walkforward import buy_and_hold_outcomes, run_forecaster_backtest
from evemarket.config import Config


def _series(prices: Sequence[float]) -> list[PricePoint]:
    return [
        PricePoint(date=f"2026-01-{index + 1:02d}", price=price)
        for index, price in enumerate(prices)
    ]


def test_run_forecaster_backtest_reuses_station_trade_profit_for_realized_outcomes() -> None:
    config = Config()
    series = _series([100.0, 250.0, 400.0, 700.0])

    def bullish(history: Sequence[PricePoint], *, horizon: int) -> Forecast:
        return Forecast(predicted_price=history[-1].price * 2, direction=1)

    outcomes = run_forecaster_backtest(series, bullish, config, horizon=1, warmup=1)

    assert len(outcomes) == 3
    for t, outcome in enumerate(outcomes):
        expected = station_trade_opportunity(
            config,
            series[t].price,
            series[t + 1].price,
            1,
        ).profit
        assert outcome.net_isk == expected


def test_run_forecaster_backtest_uses_only_point_in_time_history_windows() -> None:
    config = Config()
    series = _series([100.0, 150.0, 225.0, 350.0, 600.0])
    seen_history_lengths: list[int] = []
    seen_last_dates: list[str] = []

    def recording_bullish(history: Sequence[PricePoint], *, horizon: int) -> Forecast:
        seen_history_lengths.append(len(history))
        seen_last_dates.append(history[-1].date)
        return Forecast(predicted_price=history[-1].price * 3, direction=1)

    outcomes = run_forecaster_backtest(
        series,
        recording_bullish,
        config,
        horizon=2,
        warmup=2,
    )

    assert len(outcomes) == len(range(1, len(series) - 2))
    assert seen_history_lengths == [2, 3]
    assert seen_last_dates == ["2026-01-02", "2026-01-03"]


def test_naive_persistence_abstains_and_scores_as_empty_backtest() -> None:
    outcomes = run_forecaster_backtest(
        _series([100.0, 150.0, 225.0]),
        naive_persistence_forecast,
        Config(),
        horizon=1,
        warmup=1,
    )

    assert outcomes == []
    assert compute_metrics(outcomes).sample_size == 0


def test_correct_direction_and_net_isk_follow_realized_move() -> None:
    series = _series([100.0, 250.0, 100.0])

    def bullish(history: Sequence[PricePoint], *, horizon: int) -> Forecast:
        return Forecast(predicted_price=history[-1].price * 3, direction=1)

    outcomes = run_forecaster_backtest(series, bullish, Config(), horizon=1, warmup=1)

    assert len(outcomes) == 2
    assert outcomes[0].correct_direction is True
    assert outcomes[0].net_isk > 0
    assert outcomes[1].correct_direction is False
    assert outcomes[1].net_isk < 0


def test_run_forecaster_backtest_rejects_invalid_bounds_and_returns_empty_when_too_short() -> None:
    series = _series([100.0, 200.0])

    def bullish(history: Sequence[PricePoint], *, horizon: int) -> Forecast:
        return Forecast(predicted_price=history[-1].price * 2, direction=1)

    with pytest.raises(ValueError, match="horizon must be at least 1"):
        run_forecaster_backtest(series, bullish, Config(), horizon=0, warmup=1)
    with pytest.raises(ValueError, match="warmup must be at least 1"):
        run_forecaster_backtest(series, bullish, Config(), horizon=1, warmup=0)

    assert run_forecaster_backtest(series, bullish, Config(), horizon=2, warmup=1) == []


def test_seasonal_forecaster_runs_end_to_end_into_metrics() -> None:
    series = _series([100.0, 300.0, 120.0, 360.0, 140.0, 420.0])

    def seasonal(history: Sequence[PricePoint], *, horizon: int) -> Forecast:
        return seasonal_naive_forecast(history, horizon=horizon, season_length=2)

    outcomes = run_forecaster_backtest(series, seasonal, Config(), horizon=1, warmup=3)
    metrics = compute_metrics(outcomes)

    assert len(outcomes) >= 1
    assert metrics.sample_size == len(outcomes)
    assert math.isfinite(metrics.expectancy)


def test_buy_and_hold_outcomes_returns_one_fee_net_round_trip() -> None:
    config = Config()
    series = _series([100.0, 250.0, 400.0])

    outcomes = buy_and_hold_outcomes(series, config)

    expected = station_trade_opportunity(config, 100.0, 400.0, 1).profit
    assert len(outcomes) == 1
    assert outcomes[0].net_isk == expected
    assert outcomes[0].correct_direction is True


def test_buy_and_hold_outcomes_handles_decrease_and_short_series() -> None:
    decreasing = buy_and_hold_outcomes(_series([400.0, 100.0]), Config())

    assert len(decreasing) == 1
    assert decreasing[0].correct_direction is False
    assert buy_and_hold_outcomes([], Config()) == []
    assert buy_and_hold_outcomes(_series([100.0]), Config()) == []
