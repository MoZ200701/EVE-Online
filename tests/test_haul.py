from __future__ import annotations

import math

import pytest

from evemarket.analytics.haul import HaulQuote, scan_haul_opportunities
from evemarket.analytics.opportunity import station_trade_opportunity
from evemarket.config import Config


def _dest_price_for_unit_profit(source_price: float, unit_profit: float) -> float:
    return (unit_profit + (source_price * 1.03)) / 0.895


def test_scan_haul_cargo_bound_and_profit_per_m3() -> None:
    config = Config()
    quote = HaulQuote(
        type_id=34,
        type_name="Tritanium",
        source_price=100.0,
        dest_price=130.0,
        volume_m3=100.0,
        daily_volume=10_000.0,
    )

    result = scan_haul_opportunities([quote], config)[0]

    assert result.quantity == math.floor(config.cargo_m3 / quote.volume_m3) == 50
    assert result.total_profit > 0
    assert result.profit_per_m3 == pytest.approx(result.total_profit / (50 * 100.0))
    per_unit_cost = station_trade_opportunity(config, 100.0, 130.0, 1).cost
    assert math.floor(config.capital_isk / per_unit_cost) > result.quantity


def test_scan_haul_capital_bound() -> None:
    config = Config(capital_isk=450)
    quote = HaulQuote(34, "Tritanium", 100.0, 130.0, 1.0, 10_000.0)
    per_unit_cost = station_trade_opportunity(config, 100.0, 130.0, 1).cost

    result = scan_haul_opportunities([quote], config)[0]

    assert math.floor(config.capital_isk / per_unit_cost) < math.floor(config.cargo_m3 / 1.0)
    assert result.quantity == math.floor(config.capital_isk / per_unit_cost)


def test_scan_haul_skips_invalid_prices_volume_and_zero_quantity() -> None:
    config = Config()
    quotes = [
        HaulQuote(34, "No Source", 0.0, 130.0, 1.0, 100.0),
        HaulQuote(35, "No Dest", 100.0, 0.0, 1.0, 100.0),
        HaulQuote(36, "No Volume", 100.0, 130.0, 0.0, 100.0),
        HaulQuote(37, "Too Bulky", 100.0, 130.0, config.cargo_m3 + 1.0, 100.0),
    ]

    assert scan_haul_opportunities(quotes, config) == []


def test_scan_haul_no_spread_excluded_by_default_min_roi() -> None:
    quote = HaulQuote(34, "Tritanium", 100.0, 100.0, 1.0, 100.0)

    assert scan_haul_opportunities([quote], Config()) == []


def test_scan_haul_filters_thresholds() -> None:
    config = Config()
    quote = HaulQuote(34, "Tritanium", 100.0, 130.0, 100.0, 50.0)
    baseline = scan_haul_opportunities([quote], config)[0]

    assert scan_haul_opportunities([quote], config, min_roi=baseline.roi + 0.001) == []
    assert (
        scan_haul_opportunities(
            [quote],
            config,
            min_total_profit=baseline.total_profit + 0.01,
        )
        == []
    )
    assert scan_haul_opportunities([quote], config, min_daily_volume=quote.daily_volume + 1.0) == []
    assert (
        scan_haul_opportunities(
            [quote],
            config,
            max_days_to_sell=baseline.days_to_sell - 0.001,
        )
        == []
    )


def test_scan_haul_zero_daily_volume_days_to_sell_inf_and_finite_filter_excludes() -> None:
    quote = HaulQuote(34, "Tritanium", 100.0, 130.0, 100.0, 0.0)

    result = scan_haul_opportunities([quote], Config())[0]

    assert result.days_to_sell == float("inf")
    assert scan_haul_opportunities([quote], Config(), max_days_to_sell=1.0) == []


def test_scan_haul_sort_and_limit() -> None:
    config = Config()
    quotes = [
        HaulQuote(36, "Tie Low Id", 100.0, _dest_price_for_unit_profit(100.0, 20.0), 500.0, 1_000.0),
        HaulQuote(37, "Tie High Id", 100.0, _dest_price_for_unit_profit(100.0, 20.0), 500.0, 1_000.0),
        HaulQuote(35, "Tie Higher Roi", 100.0, _dest_price_for_unit_profit(100.0, 40.0), 1000.0, 1_000.0),
        HaulQuote(34, "Higher Total", 100.0, _dest_price_for_unit_profit(100.0, 30.0), 500.0, 1_000.0),
    ]

    results = scan_haul_opportunities(quotes, config)

    assert [result.type_id for result in results] == [34, 35, 36, 37]
    assert [result.type_id for result in scan_haul_opportunities(quotes, config, limit=1)] == [34]


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"min_roi": -0.1}, "min_roi"),
        ({"min_total_profit": -0.1}, "min_total_profit"),
        ({"min_daily_volume": -0.1}, "min_daily_volume"),
        ({"max_days_to_sell": 0}, "max_days_to_sell"),
        ({"limit": 0}, "limit"),
    ],
)
def test_scan_haul_value_errors(kwargs: dict[str, float | int], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        scan_haul_opportunities([], Config(), **kwargs)


def test_scan_haul_reuses_station_trade_profit_math() -> None:
    config = Config()
    quote = HaulQuote(34, "Tritanium", 100.0, 130.0, 100.0, 10_000.0)

    result = scan_haul_opportunities([quote], config)[0]

    expected = station_trade_opportunity(
        config,
        quote.source_price,
        quote.dest_price,
        result.quantity,
    )
    assert result.total_profit == pytest.approx(expected.profit)
