from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MacroPrice(BaseModel):
    symbol: str
    price: float | None = None
    as_of_utc: datetime | None = None
    is_market_open: bool = False
    staleness_seconds: int | None = None
    source: str = "yfinance"
    error: str | None = None


class FearGreedIndex(BaseModel):
    value: int | None = None
    classification: str | None = None
    as_of_utc: datetime | None = None
    source: str = "alternative.me"
    error: str | None = None


class EtfActivity(BaseModel):
    ticker: str
    close: float | None = None
    volume: int | None = None
    avg_volume_20d: float | None = None
    as_of_utc: datetime | None = None
    source: str = "yfinance"
    error: str | None = None


class MacroSnapshot(BaseModel):
    snapshot_id: str
    captured_at_utc: datetime
    brent: MacroPrice
    wti: MacroPrice
    dxy: MacroPrice
    us10y_yield_pct: MacroPrice
    btc_fear_greed: FearGreedIndex
    btc_etf_activity: dict[str, EtfActivity] = Field(default_factory=dict)
    fetch_errors: list[str] = Field(default_factory=list)
