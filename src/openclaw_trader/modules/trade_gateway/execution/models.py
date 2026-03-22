from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class ExecutionDecision(BaseModel):
    decision_id: str
    context_id: str
    strategy_version: str
    product_id: str
    coin: str
    action: str
    side: str
    size_pct_of_equity: float | None = None
    priority: int = 1
    urgency: str = "normal"
    valid_for_minutes: int = 10
    escalate_to_pm: bool = False
    escalation_reason: str | None = None
    notional_usd: str | None = None
    leverage: str | None = None
    reason: str | None = None


class ExecutionPlan(BaseModel):
    plan_id: str
    decision_id: str
    context_id: str | None = None
    strategy_version: str | None = None
    product_id: str
    coin: str
    action: str
    side: str
    size_pct_of_equity: float | None = None
    margin_usd: str | None = None
    notional_usd: str | None = None
    leverage: str | None = None
    preflight: dict[str, Any] = Field(default_factory=dict)


class ExecutionResult(BaseModel):
    plan_id: str
    decision_id: str | None = None
    strategy_version: str | None = None
    coin: str | None = None
    action: str | None = None
    side: str | None = None
    notional_usd: str | None = None
    success: bool
    exchange_order_id: str | None = None
    message: str | None = None
    fills: list[dict[str, Any]] = Field(default_factory=list)
    executed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    technical_failure: bool = False


class PortfolioView(BaseModel):
    total_equity_usd: str
    available_equity_usd: str
    positions: list[dict[str, Any]] = Field(default_factory=list)
