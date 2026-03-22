from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class PriceSeriesPoint(BaseModel):
    timestamp: int
    close: str


class CompressedPriceSeries(BaseModel):
    window: str
    granularity: str
    points: list[PriceSeriesPoint] = Field(default_factory=list)
    change_pct: float | None = None


class KeyLevel(BaseModel):
    label: str
    price: str
    source: str


class BreakoutRetestState(BaseModel):
    state: str = "range"
    reference_level: str | None = None
    reference_price: str | None = None


class VolatilityState(BaseModel):
    state: str = "normal"
    short_window_realized_vol: float = 0.0
    long_window_realized_vol: float = 0.0


class OrderbookDepthSnapshot(BaseModel):
    best_bid_size: str | None = None
    best_ask_size: str | None = None
    bid_depth_notional_usd: str | None = None
    ask_depth_notional_usd: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class LiquiditySnapshot(BaseModel):
    best_bid: str | None = None
    best_ask: str | None = None
    spread_bps: float | None = None
    orderbook_depth: OrderbookDepthSnapshot | None = None


class ProductMetadataSnapshot(BaseModel):
    coin: str
    product_id: str
    tick_size: str
    size_increment: str
    min_size: str | None = None
    min_notional: str
    max_leverage: str | None = None
    trading_status: str | None = None
    trading_disabled: bool = False
    cancel_only: bool = False
    limit_only: bool = False
    post_only: bool = False
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    raw: dict[str, Any] = Field(default_factory=dict)


class OpenOrderSnapshot(BaseModel):
    order_id: str
    status: str | None = None
    side: str | None = None
    order_type: str | None = None
    notional_usd: str | None = None
    limit_price: str | None = None
    base_size: str | None = None
    created_at: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class PortfolioPositionSnapshot(BaseModel):
    coin: str
    side: str
    quantity: str
    notional_usd: str
    leverage: str
    entry_price: str
    unrealized_pnl_usd: str
    position_share_pct_of_equity: float = 0.0
    opened_at: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class PortfolioSnapshot(BaseModel):
    starting_equity_usd: str = "0"
    realized_pnl_usd: str = "0"
    unrealized_pnl_usd: str = "0"
    total_equity_usd: str = "0"
    available_equity_usd: str = "0"
    total_exposure_usd: str = "0"
    open_order_hold_usd: str = "0"
    positions: list[PortfolioPositionSnapshot] = Field(default_factory=list)
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    raw: dict[str, Any] = Field(default_factory=dict)


class MarketContextNormalized(BaseModel):
    coin: str
    product_id: str
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    compressed_price_series: dict[str, CompressedPriceSeries] = Field(default_factory=dict)
    key_levels: list[KeyLevel] = Field(default_factory=list)
    breakout_retest_state: BreakoutRetestState = Field(default_factory=BreakoutRetestState)
    volatility_state: VolatilityState = Field(default_factory=VolatilityState)
    shape_summary: str = ""
    liquidity: LiquiditySnapshot = Field(default_factory=LiquiditySnapshot)
    raw: dict[str, Any] = Field(default_factory=dict)


class ExecutionHistorySnapshot(BaseModel):
    coin: str
    product_id: str
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    recent_orders: list[dict[str, Any]] = Field(default_factory=list)
    recent_fills: list[dict[str, Any]] = Field(default_factory=list)
    failure_sources: list[dict[str, Any]] = Field(default_factory=list)
    open_orders: list[OpenOrderSnapshot] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class MarketSnapshotNormalized(BaseModel):
    snapshot_id: str
    coin: str
    product_id: str
    mark_price: str
    index_price: str | None = None
    funding_rate: str | None = None
    premium: str | None = None
    open_interest: str | None = None
    day_notional_volume: str | None = None
    spread_bps: float | None = None
    trading_status: str | None = None
    trading_disabled: bool = False
    cancel_only: bool = False
    limit_only: bool = False
    post_only: bool = False
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    raw: dict[str, Any] = Field(default_factory=dict)


class AccountSnapshot(BaseModel):
    coin: str
    total_equity_usd: str
    available_equity_usd: str
    current_side: str | None = None
    current_notional_usd: str | None = None
    current_leverage: str | None = None
    current_quantity: str | None = None
    entry_price: str | None = None
    unrealized_pnl_usd: str | None = None
    liquidation_price: str | None = None
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    raw: dict[str, Any] = Field(default_factory=dict)


class DataIngestBundle(BaseModel):
    trace_id: str
    market: dict[str, MarketSnapshotNormalized]
    accounts: dict[str, AccountSnapshot]
    portfolio: PortfolioSnapshot = Field(default_factory=PortfolioSnapshot)
    market_context: dict[str, MarketContextNormalized] = Field(default_factory=dict)
    execution_history: dict[str, ExecutionHistorySnapshot] = Field(default_factory=dict)
    product_metadata: dict[str, ProductMetadataSnapshot] = Field(default_factory=dict)
