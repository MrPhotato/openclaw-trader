from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TradeAvailability(BaseModel):
    tradable: bool = True
    reasons: list[str] = Field(default_factory=list)


class RiskLimits(BaseModel):
    max_leverage: float
    max_total_exposure_pct_of_equity: float
    max_symbol_position_pct_of_equity: float
    max_order_pct_of_equity: float


class PositionRiskState(BaseModel):
    state: str = "normal"
    reasons: list[str] = Field(default_factory=list)
    thresholds: dict[str, float] = Field(default_factory=dict)


class CooldownState(BaseModel):
    active: bool = False
    until_utc: str | None = None
    reason: str | None = None


class BreakerState(BaseModel):
    active: bool = False
    reason: str | None = None
    until_utc: str | None = None


class PolicyDiagnostics(BaseModel):
    ignored_horizons: list[str] = Field(default_factory=lambda: ["1h"])
    recent_event_titles: list[str] = Field(default_factory=list)
    horizon_summaries: dict[str, dict[str, Any]] = Field(default_factory=dict)
    portfolio_exposure_pct: float = 0.0


class GuardDecision(BaseModel):
    coin: str
    trade_availability: TradeAvailability
    risk_limits: RiskLimits
    position_risk_state: PositionRiskState
    cooldown: CooldownState = Field(default_factory=CooldownState)
    breaker: BreakerState = Field(default_factory=BreakerState)
    diagnostics: PolicyDiagnostics = Field(default_factory=PolicyDiagnostics)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionAuthorization(BaseModel):
    accepted: list[dict[str, Any]] = Field(default_factory=list)
    rejected: list[dict[str, Any]] = Field(default_factory=list)
