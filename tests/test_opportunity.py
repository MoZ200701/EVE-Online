import pytest

from evemarket.analytics.fees import station_trade_fees
from evemarket.analytics.opportunity import (
    MarketBuy,
    MarketSell,
    ProfitOpportunity,
    station_trade_opportunity,
)
from evemarket.config import Config, SkillConfig


def test_market_buy_sell_and_profit_opportunity_zero_skills() -> None:
    acquisition = MarketBuy(100, 10)
    disposal = MarketSell(120, 10)
    opportunity = ProfitOpportunity(acquisition, disposal)

    assert acquisition.total_cost == pytest.approx(1030)
    assert disposal.net_proceeds == pytest.approx(1074)
    assert opportunity.cost == pytest.approx(1030)
    assert opportunity.revenue == pytest.approx(1074)
    assert opportunity.profit == pytest.approx(44)
    assert opportunity.roi == pytest.approx(44 / 1030)
    assert opportunity.quantity == 10


def test_profit_matches_station_trade_fee_total_invariant() -> None:
    buy_price = 100
    sell_price = 120
    quantity = 10
    broker_relations = 5
    accounting = 5
    faction_standing = 10.0
    corp_standing = 10.0

    opportunity = ProfitOpportunity(
        MarketBuy(
            buy_price,
            quantity,
            broker_relations=broker_relations,
            faction_standing=faction_standing,
            corp_standing=corp_standing,
        ),
        MarketSell(
            sell_price,
            quantity,
            broker_relations=broker_relations,
            accounting=accounting,
            faction_standing=faction_standing,
            corp_standing=corp_standing,
        ),
    )
    fees = station_trade_fees(
        buy_price,
        sell_price,
        quantity,
        broker_relations=broker_relations,
        accounting=accounting,
        faction_standing=faction_standing,
        corp_standing=corp_standing,
    )

    assert opportunity.profit == pytest.approx(
        (sell_price - buy_price) * quantity - fees.total
    )


def test_station_trade_opportunity_from_config() -> None:
    config = Config(
        skills=SkillConfig(broker_relations=5, accounting=5),
        standings_factional=10,
        standings_corp=10,
    )

    opportunity = station_trade_opportunity(config, 100, 120, 10)

    assert opportunity.cost == pytest.approx(1010)
    assert opportunity.revenue == pytest.approx(1147.5)
    assert opportunity.profit == pytest.approx(137.5)


def test_value_errors() -> None:
    with pytest.raises(ValueError):
        ProfitOpportunity(MarketBuy(100, 10), MarketSell(120, 5))
    with pytest.raises(ValueError):
        MarketBuy(-1, 10)
    with pytest.raises(ValueError):
        MarketSell(120, 0)
    with pytest.raises(ValueError):
        MarketBuy(100, 10, broker_relations=6).total_cost
