import math

import pytest

from evemarket.analytics.backtest import (
    BacktestMetrics,
    TradeOutcome,
    compute_metrics,
    directional_hit_rate,
    expectancy_per_trade,
    expectancy_t_stat,
    max_drawdown,
    profit_factor,
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
