from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

def _parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)

def _round_metric(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)

def _safe_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value in (None, ""):
            return Decimal(default)
        return Decimal(str(value))
    except Exception:
        return Decimal(default)

def _optional_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None

def _format_decimal_text(value: Any) -> str | None:
    decimal_value = _optional_decimal(value)
    if decimal_value is None:
        return None
    text = format(decimal_value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text

def _round_share_pct(value: float) -> float:
    return round(max(float(value), 0.0), 2)

def _format_share_range(min_share_pct: float, max_share_pct: float) -> str:
    return f"{_round_share_pct(min_share_pct)}%-{_round_share_pct(max_share_pct)}%"

def _format_amount_text(
    *,
    notional_usd: Any = None,
    leverage: Any = None,
    margin_usd: Any = None,
) -> str:
    margin_value = _optional_decimal(margin_usd)
    leverage_value = _optional_decimal(leverage)
    notional_value = _optional_decimal(notional_usd)
    if margin_value is None and notional_value is not None and leverage_value is not None and leverage_value > 0:
        margin_value = notional_value / leverage_value
    margin_text = _format_decimal_text(margin_value)
    leverage_text = _format_decimal_text(leverage_value)
    notional_text = _format_decimal_text(notional_value)
    parts: list[str] = []
    if margin_text is not None:
        parts.append(f"原始金额 {margin_text} USD")
    if leverage_text is not None and leverage_value is not None and leverage_value > 0:
        parts.append(f"杠杆 {leverage_text}x")
    if not parts and notional_text is not None:
        parts.append(f"金额记录 {notional_text} USD")
        parts.append("杠杆未知")
    return " | ".join(parts) if parts else "金额未知"

def _format_review_exit_text(review: dict[str, Any] | None) -> str | None:
    review = review or {}
    stop_loss = _format_decimal_text(review.get("stop_loss_price"))
    take_profit = _format_decimal_text(review.get("take_profit_price"))
    exit_plan = str(review.get("exit_plan") or "").strip()
    parts: list[str] = []
    if stop_loss is not None:
        parts.append(f"止损价 {stop_loss}")
    if take_profit is not None:
        parts.append(f"止盈价 {take_profit}")
    if exit_plan:
        parts.append(f"退出计划 {exit_plan}")
    return " | ".join(parts) if parts else None

def _normalize_strategy_symbol(symbol: Any) -> str:
    text = str(symbol or "").strip().upper()
    if not text:
        return ""
    if text.endswith("-PERP-INTX"):
        return text.removesuffix("-INTX")
    if text.endswith("-PERP"):
        return text
    if "-" not in text:
        return f"{text}-PERP"
    return text

def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default
