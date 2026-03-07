from __future__ import annotations

from decimal import Decimal

from .config import RiskConfig
from .models import Balance, PositionRiskStage, RiskEvaluation, SignalDecision, SignalSide


def classify_position_drawdown(drawdown_pct: float | None, risk: RiskConfig) -> PositionRiskStage:
    if drawdown_pct is None:
        return PositionRiskStage.normal
    if drawdown_pct >= risk.position_exit_drawdown_pct:
        return PositionRiskStage.exit
    if drawdown_pct >= risk.position_reduce_drawdown_pct:
        return PositionRiskStage.reduce
    if drawdown_pct >= risk.position_observe_drawdown_pct:
        return PositionRiskStage.observe
    return PositionRiskStage.normal


def _dynamic_limits(
    risk: RiskConfig,
    total_equity_usd: Decimal | None,
    current_position_quote_usd: Decimal = Decimal("0"),
) -> tuple[Decimal, Decimal | None, Decimal]:
    legacy_position_cap = Decimal(str(risk.max_position_quote_usd)) if risk.max_position_quote_usd is not None else None
    pct_cap = None
    if total_equity_usd is not None:
        pct_cap = total_equity_usd * Decimal(str(risk.max_position_pct_of_equity)) / Decimal("100")

    position_cap = pct_cap if pct_cap is not None else legacy_position_cap
    if position_cap is None:
        position_cap = Decimal(str(risk.max_order_quote_usd or 0))

    remaining_capacity = max(position_cap - current_position_quote_usd, Decimal("0"))

    order_cap = None
    if total_equity_usd is not None:
        order_cap = total_equity_usd * Decimal(str(risk.max_order_pct_of_equity)) / Decimal("100")
    elif risk.max_order_quote_usd is not None:
        order_cap = Decimal(str(risk.max_order_quote_usd))
    max_allowed = min(remaining_capacity, order_cap) if order_cap is not None else remaining_capacity
    return max_allowed, position_cap, remaining_capacity


def evaluate_signal(
    signal: SignalDecision,
    risk: RiskConfig,
    usd_balance: Balance | None,
    total_equity_usd: Decimal | None,
    daily_equity_baseline_usd: Decimal | None,
    current_position_quote_usd: Decimal = Decimal("0"),
    position_drawdown_pct: float | None = None,
) -> RiskEvaluation:
    blocked: list[str] = []
    max_allowed, _position_cap, remaining_capacity = _dynamic_limits(risk, total_equity_usd, current_position_quote_usd)
    daily_drawdown_pct = None
    if total_equity_usd is not None and daily_equity_baseline_usd and daily_equity_baseline_usd > 0:
        daily_drawdown_pct = float(((daily_equity_baseline_usd - total_equity_usd) / daily_equity_baseline_usd) * Decimal("100"))

    position_risk_stage = classify_position_drawdown(position_drawdown_pct, risk)

    if signal.product_id not in risk.symbol_whitelist:
        blocked.append("symbol_not_whitelisted")
    if signal.quote_size_usd is not None and signal.quote_size_usd > max_allowed:
        blocked.append("signal_quote_above_limit")
    if float(signal.leverage) > risk.max_leverage:
        blocked.append("leverage_above_limit")
    if signal.side == SignalSide.short:
        blocked.append("shorts_not_enabled_in_v1")
    if usd_balance and usd_balance.available < Decimal("1"):
        blocked.append("insufficient_usd_balance")
    if daily_drawdown_pct is not None and daily_drawdown_pct >= risk.daily_loss_limit_pct_of_equity:
        blocked.append("daily_drawdown_limit_exceeded")
    if position_risk_stage in {PositionRiskStage.reduce, PositionRiskStage.exit}:
        blocked.append("position_drawdown_risk_high")

    approved = not blocked and signal.side != SignalSide.flat
    reason = "approved" if approved else ",".join(blocked) or "flat_signal"
    return RiskEvaluation(
        approved=approved,
        reason=reason,
        max_allowed_quote_usd=max_allowed,
        total_equity_usd=total_equity_usd,
        daily_equity_baseline_usd=daily_equity_baseline_usd,
        daily_drawdown_pct=daily_drawdown_pct,
        current_position_quote_usd=current_position_quote_usd,
        remaining_capacity_quote_usd=remaining_capacity,
        max_order_pct_of_equity=risk.max_order_pct_of_equity,
        max_position_pct_of_equity=risk.max_position_pct_of_equity,
        position_drawdown_pct=position_drawdown_pct,
        position_risk_stage=position_risk_stage,
        blocked_rules=blocked,
    )


def evaluate_manual_buy(
    quote_size: Decimal,
    product_id: str,
    risk: RiskConfig,
    usd_balance: Balance | None,
    total_equity_usd: Decimal | None,
    daily_equity_baseline_usd: Decimal | None,
    current_position_quote_usd: Decimal = Decimal("0"),
    position_drawdown_pct: float | None = None,
) -> RiskEvaluation:
    blocked: list[str] = []
    max_allowed, _position_cap, remaining_capacity = _dynamic_limits(risk, total_equity_usd, current_position_quote_usd)
    daily_drawdown_pct = None
    if total_equity_usd is not None and daily_equity_baseline_usd and daily_equity_baseline_usd > 0:
        daily_drawdown_pct = float(((daily_equity_baseline_usd - total_equity_usd) / daily_equity_baseline_usd) * Decimal("100"))
    position_risk_stage = classify_position_drawdown(position_drawdown_pct, risk)
    if product_id not in risk.symbol_whitelist:
        blocked.append("symbol_not_whitelisted")
    if quote_size > max_allowed:
        blocked.append("quote_above_max_order_limit")
    if usd_balance and quote_size > usd_balance.available:
        blocked.append("insufficient_usd_balance")
    if daily_drawdown_pct is not None and daily_drawdown_pct >= risk.daily_loss_limit_pct_of_equity:
        blocked.append("daily_drawdown_limit_exceeded")
    if position_risk_stage in {PositionRiskStage.reduce, PositionRiskStage.exit}:
        blocked.append("position_drawdown_risk_high")
    approved = not blocked
    return RiskEvaluation(
        approved=approved,
        reason="approved" if approved else ",".join(blocked),
        max_allowed_quote_usd=max_allowed,
        total_equity_usd=total_equity_usd,
        daily_equity_baseline_usd=daily_equity_baseline_usd,
        daily_drawdown_pct=daily_drawdown_pct,
        current_position_quote_usd=current_position_quote_usd,
        remaining_capacity_quote_usd=remaining_capacity,
        max_order_pct_of_equity=risk.max_order_pct_of_equity,
        max_position_pct_of_equity=risk.max_position_pct_of_equity,
        position_drawdown_pct=position_drawdown_pct,
        position_risk_stage=position_risk_stage,
        blocked_rules=blocked,
    )
