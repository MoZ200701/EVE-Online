import pytest

from evemarket.analytics.fees import (
    TradeFees,
    broker_fee,
    broker_fee_rate,
    sales_tax_rate,
    station_trade_fees,
    station_trade_fees_from_config,
)
from evemarket.config import Config, SkillConfig


def test_broker_fee_rate_defaults_and_skill_reduction() -> None:
    assert broker_fee_rate() == pytest.approx(0.03)
    assert broker_fee_rate(broker_relations=5) == pytest.approx(0.015)


def test_broker_fee_rate_floor_and_negative_standing() -> None:
    assert (
        broker_fee_rate(
            broker_relations=5,
            faction_standing=10,
            corp_standing=10,
        )
        == 0.01
    )
    assert broker_fee_rate(faction_standing=-10) > 0.03


def test_sales_tax_rate_accounting_reduction() -> None:
    assert sales_tax_rate(accounting=0) == pytest.approx(0.075)
    assert sales_tax_rate(accounting=5) == pytest.approx(0.03375)


def test_station_trade_fees_zero_skills() -> None:
    fees = station_trade_fees(100, 120, 10)

    assert fees.buy_broker_fee == pytest.approx(30)
    assert fees.sell_broker_fee == pytest.approx(36)
    assert fees.sales_tax == pytest.approx(90)
    assert fees.total == pytest.approx(156)


def test_station_trade_fees_from_config_delegates() -> None:
    config = Config(
        skills=SkillConfig(broker_relations=5, accounting=5),
        standings_factional=10,
        standings_corp=10,
    )

    assert station_trade_fees_from_config(config, 100, 120, 10) == TradeFees(
        buy_broker_fee=pytest.approx(10),
        sell_broker_fee=pytest.approx(12),
        sales_tax=pytest.approx(40.5),
        total=pytest.approx(62.5),
    )
    assert station_trade_fees_from_config(config, 100, 120, 10) == station_trade_fees(
        100,
        120,
        10,
        broker_relations=5,
        accounting=5,
        faction_standing=10,
        corp_standing=10,
    )


@pytest.mark.parametrize(
    ("call", "kwargs"),
    [
        (broker_fee_rate, {"broker_relations": 6}),
        (sales_tax_rate, {"accounting": 6}),
        (broker_fee_rate, {"faction_standing": 11}),
    ],
)
def test_rate_validation_errors(call: object, kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        call(**kwargs)  # type: ignore[operator]


def test_amount_validation_errors() -> None:
    with pytest.raises(ValueError):
        broker_fee(-1)
    with pytest.raises(ValueError):
        station_trade_fees(100, 120, 0)
