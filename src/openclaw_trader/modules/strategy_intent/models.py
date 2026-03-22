from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StrategyTarget(BaseModel):
    coin: str
    product_id: str
    bias: str
    target_position_share_pct: float
    max_position_share_pct: float
    rationale: str


class StrategyIntent(BaseModel):
    strategy_version: str
    change_reason: str
    targets: list[StrategyTarget] = Field(default_factory=list)
    thesis: str
    invalidation: str
    scheduled_rechecks: list[dict[str, Any]] = Field(default_factory=list)


class ExecutionContext(BaseModel):
    context_id: str
    strategy_version: str
    coin: str
    product_id: str
    target_bias: str
    target_position_share_pct: float
    max_position_share_pct: float
    rationale: str
    market_snapshot: dict[str, Any] = Field(default_factory=dict)
    account_snapshot: dict[str, Any] = Field(default_factory=dict)
    risk_limits: dict[str, Any] = Field(default_factory=dict)
    position_risk_state: dict[str, Any] = Field(default_factory=dict)
    forecast_snapshot: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
