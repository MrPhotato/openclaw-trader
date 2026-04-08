from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, Field


class TradeAvailability(BaseModel):
    tradable: bool = True
    reasons: list[str] = Field(default_factory=list)


class RiskLimits(BaseModel):
    max_leverage: float
    max_total_exposure_pct_of_exposure_budget: float = Field(
        validation_alias=AliasChoices(
            "max_total_exposure_pct_of_exposure_budget",
            "max_total_exposure_pct_of_equity",
        )
    )
    max_symbol_position_pct_of_exposure_budget: float = Field(
        validation_alias=AliasChoices(
            "max_symbol_position_pct_of_exposure_budget",
            "max_symbol_position_pct_of_equity",
        )
    )
    max_order_pct_of_exposure_budget: float = Field(
        validation_alias=AliasChoices(
            "max_order_pct_of_exposure_budget",
            "max_order_pct_of_equity",
        )
    )


class PositionRiskState(BaseModel):
    state: str = "normal"
    reasons: list[str] = Field(default_factory=list)
    thresholds: dict[str, float] = Field(default_factory=dict)
    drawdown_pct: float = 0.0
    reference_price: str | None = None
    reference_kind: str | None = None
    current_mark_price: str | None = None
    lock_mode: str | None = None
    lock_strategy_key: str | None = None


class PortfolioRiskState(BaseModel):
    state: str = "normal"
    reasons: list[str] = Field(default_factory=list)
    thresholds: dict[str, float] = Field(default_factory=dict)
    drawdown_pct: float = 0.0
    current_equity_usd: str = "0"
    day_peak_equity_usd: str = "0"
    portfolio_day_utc: str | None = None
    lock_mode: str | None = None
    lock_strategy_key: str | None = None


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
    portfolio_exposure_pct_of_exposure_budget: float = Field(
        default=0.0,
        validation_alias=AliasChoices(
            "portfolio_exposure_pct_of_exposure_budget",
            "portfolio_exposure_pct",
        ),
    )


class GuardDecision(BaseModel):
    coin: str
    trade_availability: TradeAvailability
    risk_limits: RiskLimits
    position_risk_state: PositionRiskState
    portfolio_risk_state: PortfolioRiskState = Field(default_factory=PortfolioRiskState)
    cooldown: CooldownState = Field(default_factory=CooldownState)
    breaker: BreakerState = Field(default_factory=BreakerState)
    diagnostics: PolicyDiagnostics = Field(default_factory=PolicyDiagnostics)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionAuthorization(BaseModel):
    accepted: list[dict[str, Any]] = Field(default_factory=list)
    rejected: list[dict[str, Any]] = Field(default_factory=list)
