from __future__ import annotations

from decimal import Decimal


def exposure_budget_usd(*, total_equity_usd: object | None, max_leverage: object | None) -> Decimal:
    equity = _decimal(total_equity_usd)
    leverage = _decimal(max_leverage, default="1")
    if equity <= 0:
        return Decimal("0")
    if leverage <= 0:
        leverage = Decimal("1")
    return equity * leverage


def pct_to_notional_usd(
    *,
    pct_of_exposure_budget: object | None,
    total_equity_usd: object | None,
    max_leverage: object | None,
) -> Decimal:
    budget = exposure_budget_usd(total_equity_usd=total_equity_usd, max_leverage=max_leverage)
    pct = _decimal(pct_of_exposure_budget)
    if budget <= 0 or pct <= 0:
        return Decimal("0")
    return (budget * pct) / Decimal("100")


def notional_to_pct_of_exposure_budget(
    *,
    notional_usd: object | None,
    total_equity_usd: object | None,
    max_leverage: object | None,
) -> float:
    budget = exposure_budget_usd(total_equity_usd=total_equity_usd, max_leverage=max_leverage)
    notional = _decimal(notional_usd)
    if budget <= 0 or notional <= 0:
        return 0.0
    return float((notional / budget) * Decimal("100"))


def _decimal(value: object | None, *, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    text = str(value).strip()
    if not text:
        return Decimal(default)
    return Decimal(text)
