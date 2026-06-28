"""Deterministic market fee calculations."""

from __future__ import annotations

from dataclasses import dataclass

from evemarket.config import Config

BASE_BROKER_FEE = 0.03
BROKER_RELATIONS_REDUCTION_PER_LEVEL = 0.003
FACTION_STANDING_REDUCTION_PER_POINT = 0.0003
CORP_STANDING_REDUCTION_PER_POINT = 0.0002
MIN_BROKER_FEE = 0.01
BASE_SALES_TAX = 0.075
ACCOUNTING_REDUCTION_PER_LEVEL = 0.11


def _validate_skill_level(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 5:
        raise ValueError(f"{name} must be an integer from 0 to 5")


def _validate_standing(value: float, name: str) -> None:
    if not -10.0 <= value <= 10.0:
        raise ValueError(f"{name} must be from -10.0 to 10.0")


def broker_fee_rate(
    *,
    broker_relations: int = 0,
    faction_standing: float = 0.0,
    corp_standing: float = 0.0,
) -> float:
    """Return the broker fee rate for a limit order."""
    _validate_skill_level(broker_relations, "broker_relations")
    _validate_standing(faction_standing, "faction_standing")
    _validate_standing(corp_standing, "corp_standing")

    rate = (
        BASE_BROKER_FEE
        - BROKER_RELATIONS_REDUCTION_PER_LEVEL * broker_relations
        - FACTION_STANDING_REDUCTION_PER_POINT * faction_standing
        - CORP_STANDING_REDUCTION_PER_POINT * corp_standing
    )
    return max(rate, MIN_BROKER_FEE)


def sales_tax_rate(*, accounting: int = 0) -> float:
    """Return the sales tax rate for a completed sale."""
    _validate_skill_level(accounting, "accounting")
    return BASE_SALES_TAX * (1 - ACCOUNTING_REDUCTION_PER_LEVEL * accounting)


def broker_fee(
    order_value: float,
    *,
    broker_relations: int = 0,
    faction_standing: float = 0.0,
    corp_standing: float = 0.0,
) -> float:
    """Return broker fee ISK for an order value."""
    if order_value < 0:
        raise ValueError("order_value must be non-negative")
    return order_value * broker_fee_rate(
        broker_relations=broker_relations,
        faction_standing=faction_standing,
        corp_standing=corp_standing,
    )


def sales_tax(sale_value: float, *, accounting: int = 0) -> float:
    """Return sales tax ISK for a sale value."""
    if sale_value < 0:
        raise ValueError("sale_value must be non-negative")
    return sale_value * sales_tax_rate(accounting=accounting)


@dataclass(frozen=True)
class TradeFees:
    """Fee breakdown for a station-trade round trip."""

    buy_broker_fee: float
    sell_broker_fee: float
    sales_tax: float
    total: float


def station_trade_fees(
    buy_price: float,
    sell_price: float,
    quantity: int,
    *,
    broker_relations: int = 0,
    accounting: int = 0,
    faction_standing: float = 0.0,
    corp_standing: float = 0.0,
) -> TradeFees:
    """Return fees for buy-order then sell-order station trading."""
    if buy_price < 0:
        raise ValueError("buy_price must be non-negative")
    if sell_price < 0:
        raise ValueError("sell_price must be non-negative")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise ValueError("quantity must be an integer of at least 1")

    buy_value = buy_price * quantity
    sell_value = sell_price * quantity
    buy_broker_fee = broker_fee(
        buy_value,
        broker_relations=broker_relations,
        faction_standing=faction_standing,
        corp_standing=corp_standing,
    )
    sell_broker_fee = broker_fee(
        sell_value,
        broker_relations=broker_relations,
        faction_standing=faction_standing,
        corp_standing=corp_standing,
    )
    tax_amount = sales_tax(sell_value, accounting=accounting)
    total = buy_broker_fee + sell_broker_fee + tax_amount
    return TradeFees(buy_broker_fee, sell_broker_fee, tax_amount, total)


def station_trade_fees_from_config(
    config: Config,
    buy_price: float,
    sell_price: float,
    quantity: int,
) -> TradeFees:
    """Return station-trade fees using configured skills and standings."""
    return station_trade_fees(
        buy_price,
        sell_price,
        quantity,
        broker_relations=config.skills.broker_relations,
        accounting=config.skills.accounting,
        faction_standing=config.standings_factional,
        corp_standing=config.standings_corp,
    )
