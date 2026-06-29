import math

import pytest

from evemarket.analytics.backtest import (
    BacktestMetrics,
    Forecast,
    PricePoint,
    TradeOutcome,
    compute_metrics,
    directional_hit_rate,
    expectancy_per_trade,
    expectancy_t_stat,
    max_drawdown,
    naive_persistence_forecast,
    profit_factor,
    seasonal_naive_forecast,
    total_net_isk,
)


def test_backtest_metrics_for_hand_worked_outcomes() -> None:
    outcomes = [
        TradeOutcome(net_isk=100.0, correct_direction=True),
        TradeOutcome(net_isk=-40.0, correct_direction=False),
        TradeOutcome(net_isk=60.0, correct_direction=True),
        TradeOutcome(net_isk=-20.0, correct_direction=False),
    ]

    assert total_net_isk(outcomes) == 100.0
    assert expectancy_per_trade(outcomes) == 25.0
    assert directional_hit_rate(outcomes) == 0.5
    assert profit_factor(outcomes) == pytest.approx(160.0 / 60.0)
    assert max_drawdown(outcomes) == 40.0
    assert expectancy_t_stat(outcomes) > 0

    metrics = compute_metrics(outcomes)

    assert metrics == BacktestMetrics(
        sample_size=4,
        hit_rate=0.5,
        expectancy=25.0,
        profit_factor=pytest.approx(160.0 / 60.0),
        max_drawdown=40.0,
        total_net_isk=100.0,
        expectancy_t_stat=metrics.expectancy_t_stat,
    )


def test_max_drawdown_is_zero_for_monotonic_up_equity() -> None:
    outcomes = [
        TradeOutcome(net_isk=10.0, correct_direction=True),
        TradeOutcome(net_isk=20.0, correct_direction=True),
        TradeOutcome(net_isk=30.0, correct_direction=True),
    ]

    assert max_drawdown(outcomes) == 0.0


def test_profit_factor_edges() -> None:
    all_wins = [
        TradeOutcome(net_isk=10.0, correct_direction=True),
        TradeOutcome(net_isk=20.0, correct_direction=True),
    ]
    all_losses = [
        TradeOutcome(net_isk=-10.0, correct_direction=False),
        TradeOutcome(net_isk=-20.0, correct_direction=False),
    ]

    assert math.isinf(profit_factor(all_wins))
    assert profit_factor(all_losses) == 0.0


def test_expectancy_t_stat_is_zero_when_undefined() -> None:
    one_trade = [TradeOutcome(net_isk=10.0, correct_direction=True)]
    zero_variance = [
        TradeOutcome(net_isk=10.0, correct_direction=True),
        TradeOutcome(net_isk=10.0, correct_direction=True),
        TradeOutcome(net_isk=10.0, correct_direction=True),
    ]

    assert expectancy_t_stat(one_trade) == 0.0
    assert expectancy_t_stat(zero_variance) == 0.0


def test_compute_metrics_empty_outcomes_represents_abstention() -> None:
    metrics = compute_metrics([])

    assert metrics.sample_size == 0
    assert math.isnan(metrics.hit_rate)
    assert math.isnan(metrics.expectancy)
    assert math.isnan(metrics.profit_factor)
    assert metrics.max_drawdown == 0.0
    assert metrics.total_net_isk == 0.0
    assert math.isnan(metrics.expectancy_t_stat)


@pytest.mark.parametrize(
    "metric",
    [
        directional_hit_rate,
        expectancy_per_trade,
        profit_factor,
        max_drawdown,
        total_net_isk,
        expectancy_t_stat,
    ],
)
def test_individual_metric_functions_reject_empty_outcomes(metric) -> None:
    with pytest.raises(ValueError):
        metric([])


def test_naive_persistence_forecast_predicts_last_price_and_flat_direction() -> None:
    series = [
        PricePoint(date="2026-01-01", price=100.0),
        PricePoint(date="2026-01-02", price=112.5),
    ]

    forecast = naive_persistence_forecast(series, horizon=30)

    assert forecast == Forecast(predicted_price=112.5, direction=0)


@pytest.mark.parametrize(
    ("horizon", "expected_price", "expected_direction"),
    [
        (1, 10.0, -1),
        (7, 70.0, 0),
        (8, 10.0, -1),
    ],
)
def test_seasonal_naive_forecast_uses_prior_season_index(
    horizon: int,
    expected_price: float,
    expected_direction: int,
) -> None:
    series = [
        PricePoint(date="2026-01-01", price=10.0),
        PricePoint(date="2026-01-02", price=20.0),
        PricePoint(date="2026-01-03", price=30.0),
        PricePoint(date="2026-01-04", price=40.0),
        PricePoint(date="2026-01-05", price=50.0),
        PricePoint(date="2026-01-06", price=60.0),
        PricePoint(date="2026-01-07", price=70.0),
    ]

    forecast = seasonal_naive_forecast(series, horizon=horizon, season_length=7)

    assert forecast.predicted_price == expected_price
    assert forecast.direction == expected_direction


def test_seasonal_naive_forecast_direction_can_be_up_or_flat() -> None:
    series = [
        PricePoint(date="2026-01-01", price=100.0),
        PricePoint(date="2026-01-02", price=125.0),
        PricePoint(date="2026-01-03", price=100.0),
    ]

    up_forecast = seasonal_naive_forecast(series, horizon=1, season_length=2)
    flat_forecast = seasonal_naive_forecast(series, horizon=2, season_length=2)

    assert up_forecast == Forecast(predicted_price=125.0, direction=1)
    assert flat_forecast == Forecast(predicted_price=100.0, direction=0)


@pytest.mark.parametrize(
    ("series", "horizon", "match"),
    [
        ([], 1, "series must not be empty"),
        ([PricePoint(date="2026-01-01", price=100.0)], 0, "horizon must be at least 1"),
    ],
)
def test_naive_persistence_forecast_rejects_invalid_inputs(
    series: list[PricePoint],
    horizon: int,
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        naive_persistence_forecast(series, horizon=horizon)


@pytest.mark.parametrize(
    ("series", "horizon", "season_length", "match"),
    [
        ([], 1, 7, "series must not be empty"),
        ([PricePoint(date="2026-01-01", price=100.0)], 0, 7, "horizon must be at least 1"),
        ([PricePoint(date="2026-01-01", price=100.0)], 1, 0, "season_length must be at least 1"),
        (
            [PricePoint(date="2026-01-01", price=100.0)],
            1,
            7,
            "series too short for seasonal_naive at this horizon/season_length",
        ),
    ],
)
def test_seasonal_naive_forecast_rejects_invalid_inputs(
    series: list[PricePoint],
    horizon: int,
    season_length: int,
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        seasonal_naive_forecast(series, horizon=horizon, season_length=season_length)
