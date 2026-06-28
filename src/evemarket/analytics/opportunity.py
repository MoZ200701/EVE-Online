"""Profit opportunity abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from evemarket.analytics.fees import broker_fee, sales_tax
from evemarket.config import Config


class Acquisition(ABC):
    """How an item is obtained and what it costs."""

    quantity: int

    @property
    @abstractmethod
    def total_cost(self) -> float:
        """Return all-in ISK cost for the acquired quantity."""


class Disposal(ABC):
    """How an item is sold and what it returns."""

    quantity: int

    @property
    @abstractmethod
    def net_proceeds(self) -> float:
        """Return ISK received after disposal-side fees."""


def _validate_price_quantity(price: float, quantity: int) -> None:
    if price < 0:
        raise ValueError("price must be non-negative")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise ValueError("quantity must be an integer of at least 1")


@dataclass(frozen=True)
class MarketBuy(Acquisition):
    """Market acquisition through a limit buy order."""

    price: float
    quantity: int
    broker_relations: int = 0
    faction_standing: float = 0.0
    corp_standing: float = 0.0

    def __post_init__(self) -> None:
        _validate_price_quantity(self.price, self.quantity)

    @property
    def gross_value(self) -> float:
        """Return buy order value before fees."""
        return self.price * self.quantity

    @property
    def total_cost(self) -> float:
        """Return gross buy value plus buy-side broker fee."""
        return self.gross_value + broker_fee(
            self.gross_value,
            broker_relations=self.broker_relations,
            faction_standing=self.faction_standing,
            corp_standing=self.corp_standing,
        )


@dataclass(frozen=True)
class MarketSell(Disposal):
    """Market disposal through a limit sell order."""

    price: float
    quantity: int
    broker_relations: int = 0
    accounting: int = 0
    faction_standing: float = 0.0
    corp_standing: float = 0.0

    def __post_init__(self) -> None:
        _validate_price_quantity(self.price, self.quantity)

    @property
    def gross_value(self) -> float:
        """Return sell order value before fees."""
        return self.price * self.quantity

    @property
    def net_proceeds(self) -> float:
        """Return gross sell value minus broker fee and sales tax."""
        return (
            self.gross_value
            - broker_fee(
                self.gross_value,
                broker_relations=self.broker_relations,
                faction_standing=self.faction_standing,
                corp_standing=self.corp_standing,
            )
            - sales_tax(self.gross_value, accounting=self.accounting)
        )


@dataclass(frozen=True)
class ProfitOpportunity:
    """Trade opportunity pairing acquisition and disposal."""

    acquisition: Acquisition
    disposal: Disposal

    def __post_init__(self) -> None:
        if self.acquisition.quantity != self.disposal.quantity:
            raise ValueError("acquisition and disposal quantities must match")

    @property
    def quantity(self) -> int:
        """Return the traded quantity."""
        return self.acquisition.quantity

    @property
    def cost(self) -> float:
        """Return all-in acquisition cost."""
        return self.acquisition.total_cost

    @property
    def revenue(self) -> float:
        """Return net disposal proceeds."""
        return self.disposal.net_proceeds

    @property
    def profit(self) -> float:
        """Return net profit after all modeled fees."""
        return self.revenue - self.cost

    @property
    def roi(self) -> float:
        """Return profit over cost, or 0.0 for zero-cost trades."""
        if self.cost <= 0:
            return 0.0
        return self.profit / self.cost


def station_trade_opportunity(
    config: Config,
    buy_price: float,
    sell_price: float,
    quantity: int,
) -> ProfitOpportunity:
    """Return a station-trade opportunity using configured skills."""
    acquisition = MarketBuy(
        buy_price,
        quantity,
        broker_relations=config.skills.broker_relations,
        faction_standing=config.standings_factional,
        corp_standing=config.standings_corp,
    )
    disposal = MarketSell(
        sell_price,
        quantity,
        broker_relations=config.skills.broker_relations,
        accounting=config.skills.accounting,
        faction_standing=config.standings_factional,
        corp_standing=config.standings_corp,
    )
    return ProfitOpportunity(acquisition, disposal)
