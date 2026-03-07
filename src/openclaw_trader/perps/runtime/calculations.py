from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


def margin_to_notional(margin_usd: Decimal, leverage: Decimal) -> Decimal:
    if leverage <= 0:
        return Decimal("0")
    return max(margin_usd, Decimal("0")) * leverage


def notional_to_margin(notional_usd: Decimal, leverage: Decimal) -> Decimal:
    if leverage <= 0:
        return Decimal("0")
    return max(notional_usd, Decimal("0")) / leverage


def round_leverage_to_step(value: Decimal, *, step: Decimal = Decimal("0.5")) -> Decimal:
    if step <= 0:
        return value
    return (value / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step
