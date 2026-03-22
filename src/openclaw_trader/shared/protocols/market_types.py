from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class Candle(BaseModel):
    start: int
    low: Decimal
    high: Decimal
    open: Decimal
    close: Decimal
    volume: Decimal


class ProductSnapshot(BaseModel):
    product_id: str
    price: Decimal
    base_increment: Decimal
    quote_increment: Decimal
    quote_min_size: Decimal
    quote_max_size: Decimal | None = None
    base_min_size: Decimal | None = None
    base_max_size: Decimal | None = None
    status: str | None = None
    trading_disabled: bool = False
    cancel_only: bool = False
    limit_only: bool = False
    post_only: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)


class Balance(BaseModel):
    currency: str
    available: Decimal
    hold: Decimal = Decimal("0")
    account_uuid: str | None = None
    retail_portfolio_id: str | None = None


class OrderResult(BaseModel):
    success: bool
    order_id: str | None = None
    preview_id: str | None = None
    product_id: str | None = None
    side: str | None = None
    message: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class MarketSnapshot(BaseModel):
    product: ProductSnapshot
    candles: list[Candle]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
