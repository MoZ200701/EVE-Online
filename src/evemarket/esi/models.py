"""Pydantic models for ESI payloads."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class MarketOrder(BaseModel):
    """A market order from ESI's regional orders endpoint."""

    order_id: int
    type_id: int
    is_buy_order: bool
    price: float
    volume_remain: int
    volume_total: int
    min_volume: int
    location_id: int
    system_id: int | None = None
    range: str
    duration: int
    issued: datetime


class MarketHistoryDay(BaseModel):
    """One daily market-history row from ESI."""

    date: date
    average: float
    highest: float
    lowest: float
    order_count: int
    volume: int


class MarketPrice(BaseModel):
    """One global market price row from ESI."""

    type_id: int
    adjusted_price: float | None = None
    average_price: float | None = None
