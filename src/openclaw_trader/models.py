from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class TraderMode(str, Enum):
    paused = "paused"
    paper = "paper"
    live = "live"


class EntryWorkflowMode(str, Enum):
    observe = "observe"
    confirm = "confirm"
    auto = "auto"


class SignalSide(str, Enum):
    long = "long"
    short = "short"
    flat = "flat"


class RiskProfile(str, Enum):
    conservative = "conservative"
    normal = "normal"
    defensive = "defensive"


class PositionRiskStage(str, Enum):
    normal = "normal"
    observe = "observe"
    reduce = "reduce"
    exit = "exit"


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


class MarketSnapshot(BaseModel):
    product: ProductSnapshot
    candles: list[Candle]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class NewsItem(BaseModel):
    source: str
    title: str
    url: str
    published_at: datetime | None = None
    summary: str | None = None
    tags: list[str] = Field(default_factory=list)
    severity: Literal["low", "medium", "high"] = "low"
    layer: str = "news"


class SignalDecision(BaseModel):
    product_id: str
    side: SignalSide
    confidence: float = 0.0
    reason: str
    quote_size_usd: Decimal | None = None
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    leverage: Decimal = Decimal("1")
    risk_profile: RiskProfile = RiskProfile.normal
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


class RiskEvaluation(BaseModel):
    approved: bool
    reason: str
    max_allowed_quote_usd: Decimal
    total_equity_usd: Decimal | None = None
    daily_equity_baseline_usd: Decimal | None = None
    daily_drawdown_pct: float | None = None
    current_position_quote_usd: Decimal | None = None
    remaining_capacity_quote_usd: Decimal | None = None
    max_order_pct_of_equity: float | None = None
    max_position_pct_of_equity: float | None = None
    max_order_share_pct_of_exposure_budget: float | None = None
    max_position_share_pct_of_exposure_budget: float | None = None
    position_drawdown_pct: float | None = None
    position_risk_stage: PositionRiskStage = PositionRiskStage.normal
    blocked_rules: list[str] = Field(default_factory=list)


class EmergencyExitDecision(BaseModel):
    should_exit: bool
    reason: str
    triggers: list[str] = Field(default_factory=list)
    total_equity_usd: Decimal | None = None
    daily_equity_baseline_usd: Decimal | None = None
    daily_drawdown_pct: float | None = None
    current_position_quote_usd: Decimal | None = None
    position_peak_quote_usd: Decimal | None = None
    position_drawdown_pct: float | None = None
    position_risk_stage: PositionRiskStage = PositionRiskStage.normal
    latest_exchange_status_title: str | None = None
    latest_exchange_status_severity: str | None = None


class AutopilotPhase(str, Enum):
    heartbeat = "heartbeat"
    observe = "observe"
    confirm = "confirm"
    trade = "trade"
    panic_exit = "panic_exit"


class AutopilotDecision(BaseModel):
    phase: AutopilotPhase
    notify_user: bool
    reason: str
    product_id: str
    flow_mode: EntryWorkflowMode
    preview_generated: bool = False
    signal: SignalDecision | None = None
    risk: RiskEvaluation | None = None
    panic: EmergencyExitDecision | None = None
    latest_news: list[NewsItem] = Field(default_factory=list)
    preview: dict[str, Any] | None = None


class LlmTradeReviewOrderDecision(BaseModel):
    product_id: str
    decision: Literal["approve", "reject", "observe"]
    size_scale: float = 1.0
    reason: str
    stop_loss_price: Decimal | None = None
    take_profit_price: Decimal | None = None
    exit_plan: str | None = None


class LlmTradeReviewDecision(BaseModel):
    decision: Literal["approve", "reject", "observe"]
    size_scale: float = 1.0
    reason: str
    orders: list[LlmTradeReviewOrderDecision] = Field(default_factory=list)


class OrderPreviewRequest(BaseModel):
    product_id: str
    side: Literal["BUY", "SELL"]
    quote_size: Decimal | None = None
    base_size: Decimal | None = None


class OrderResult(BaseModel):
    success: bool
    order_id: str | None = None
    preview_id: str | None = None
    product_id: str | None = None
    side: str | None = None
    message: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class PerpSnapshot(BaseModel):
    exchange: str
    coin: str
    mark_price: Decimal
    oracle_price: Decimal
    mid_price: Decimal | None = None
    funding_rate: Decimal | None = None
    premium: Decimal | None = None
    open_interest: Decimal | None = None
    max_leverage: Decimal | None = None
    day_notional_volume: Decimal | None = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw: dict[str, Any] = Field(default_factory=dict)


class PerpPaperPosition(BaseModel):
    exchange: str
    coin: str
    side: Literal["long", "short"]
    notional_usd: Decimal
    leverage: Decimal
    entry_price: Decimal
    quantity: Decimal
    margin_used_usd: Decimal
    opened_at: datetime
    raw: dict[str, Any] = Field(default_factory=dict)


class PerpPaperAccount(BaseModel):
    exchange: str
    coin: str
    starting_equity_usd: Decimal
    realized_pnl_usd: Decimal
    unrealized_pnl_usd: Decimal
    total_equity_usd: Decimal
    available_equity_usd: Decimal
    position: PerpPaperPosition | None = None
    mark_price: Decimal | None = None


class PerpPaperPortfolio(BaseModel):
    exchange: str
    starting_equity_usd: Decimal
    realized_pnl_usd: Decimal
    unrealized_pnl_usd: Decimal
    total_equity_usd: Decimal
    available_equity_usd: Decimal
    total_exposure_usd: Decimal
    positions: list[PerpPaperPosition] = Field(default_factory=list)


class PerpPaperOrderResult(BaseModel):
    success: bool
    exchange: str
    coin: str
    action: Literal["open", "add", "reduce", "close", "open_live"]
    side: Literal["long", "short"] | None = None
    notional_usd: Decimal | None = None
    leverage: Decimal | None = None
    price: Decimal | None = None
    realized_pnl_usd: Decimal | None = None
    message: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
