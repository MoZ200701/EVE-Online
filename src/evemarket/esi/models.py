"""Pydantic models for ESI payloads."""

from __future__ import annotations

from datetime import datetime

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
