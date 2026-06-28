import pytest

from evemarket.analytics.station_trade import (
    MarketQuote,
    StationTradeResult,
    scan_station_trades,
)
from evemarket.config import Config


def test_scan_station_trades_per_unit_economics_zero_skills() -> None:
    result = scan_station_trades(
        [
            MarketQuote(
                type_id=34,
                type_name="Tritanium",
                best_bid=100,
                best_ask=120,
                daily_volume=1_000_000,
            )
        ],
        Config(),
    )

    assert result == [
        StationTradeResult(
            type_id=34,
            type_name="Tritanium",
            buy_price=100,
            sell_price=120,
            spread=pytest.approx(20),
            unit_profit=pytest.approx(4.4),
            roi=pytest.approx(4.4 / 103),
            daily_volume=1_000_000,
        )
    ]


def test_scan_station_trades_skips_no_market_quotes() -> None:
    results = scan_station_trades(
        [
            MarketQuote(34, "Tritanium", 0, 120, 1_000_000),
            MarketQuote(35, "Pyerite", 100, 0, 1_000_000),
            MarketQuote(36, "Mexallon", 100, 120, 1_000_000),
        ],
        Config(),
    )

    assert [result.type_id for result in results] == [36]


def test_scan_station_trades_threshold_filters() -> None:
    quotes = [
        MarketQuote(34, "Tritanium", 100, 120, 1_000_000),
    ]

    assert scan_station_trades(quotes, Config())
    assert scan_station_trades(quotes, Config(), min_unit_profit=5) == []
    assert scan_station_trades(quotes, Config(), min_roi=0.05) == []
    assert scan_station_trades(quotes, Config(), min_daily_volume=2_000_000) == []


def test_scan_station_trades_sorts_and_limits() -> None:
    quotes = [
        MarketQuote(34, "Tritanium", 100, 120, 500_000),
        MarketQuote(35, "Pyerite", 100, 130, 100_000),
        MarketQuote(36, "Mexallon", 100, 120, 1_000_000),
        MarketQuote(37, "Isogen", 100, 120, 1_000_000),
    ]

    results = scan_station_trades(quotes, Config())

    assert [result.type_id for result in results] == [35, 36, 37, 34]
    assert [result.type_id for result in scan_station_trades(quotes, Config(), limit=2)] == [
        35,
        36,
    ]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_roi": -1},
        {"min_unit_profit": -1},
        {"min_daily_volume": -1},
        {"limit": 0},
    ],
)
def test_scan_station_trades_value_errors(kwargs: dict[str, float | int]) -> None:
    with pytest.raises(ValueError):
        scan_station_trades([], Config(), **kwargs)
