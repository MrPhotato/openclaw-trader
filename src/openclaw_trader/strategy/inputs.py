from __future__ import annotations

from typing import Any

from ..config import StrategyConfig
from .formatting import _format_share_range, _round_share_pct


def _flat_signal_context(signal: dict[str, Any]) -> tuple[str, str | None]:
    metadata = signal.get("metadata") or {}
    try:
        confidence = float(signal.get("confidence", 0.0) or 0.0)
    except Exception:
        confidence = 0.0
    try:
        prob_short = float(metadata.get("prob_short", 0.0) or 0.0)
    except Exception:
        prob_short = 0.0
    try:
        prob_long = float(metadata.get("prob_long", 0.0) or 0.0)
    except Exception:
        prob_long = 0.0
    directional_prob = max(prob_short, prob_long)
    direction_hint = None
    if directional_prob > 0:
        direction_hint = "short" if prob_short >= prob_long else "long"
    if confidence >= 0.85 and directional_prob < 0.15:
        return "true_flat", None
    if directional_prob >= 0.25:
        return "breakout_watch", direction_hint
    return "direction_pending", direction_hint


def _perp_recommended_limits(item: dict[str, Any], strategy: StrategyConfig) -> dict[str, Any]:
    signal = item.get("signal") or {}
    risk = item.get("risk") or {}
    snapshot_price = item.get("price")
    funding_rate = item.get("funding_rate")

    side = str(signal.get("side", "flat")).lower()
    confidence = float(signal.get("confidence", 0.0) or 0.0)
    risk_stage = str(risk.get("position_risk_stage", "normal")).lower()

    if side == "flat":
        signal_context, direction_hint = _flat_signal_context(signal)
        min_position_share_pct = 0.0
        max_position_share_pct = strategy.neutral_position_share_pct
        order_share_pct = strategy.neutral_order_share_pct
        if signal_context == "true_flat":
            reason = "当前是真 flat，无明确方向优势，默认目标仓位为 0。"
        elif signal_context == "breakout_watch":
            hint = f"，潜在方向偏{direction_hint}" if direction_hint else ""
            reason = f"当前仍是 flat，但属于 breakout_watch{hint}；重点观察是否形成方向确认，默认目标仓位为 0。"
        else:
            hint = f"，潜在方向偏{direction_hint}" if direction_hint else ""
            reason = f"当前仍是 flat，但属于 direction_pending{hint}；暂不默认配仓，等待方向确认。"
    elif confidence >= strategy.strong_signal_confidence:
        signal_context = "directional_strong"
        direction_hint = side
        min_position_share_pct = strategy.strong_signal_min_position_share_pct
        max_position_share_pct = strategy.strong_signal_max_position_share_pct
        order_share_pct = strategy.strong_signal_order_share_pct
        reason = "信号强，参考目标仓位区间可取 40%-60%。"
    elif confidence >= strategy.weak_signal_confidence:
        signal_context = "directional_medium"
        direction_hint = side
        min_position_share_pct = strategy.medium_signal_min_position_share_pct
        max_position_share_pct = strategy.medium_signal_max_position_share_pct
        order_share_pct = strategy.medium_signal_order_share_pct
        reason = "信号较强，参考目标仓位区间可取 20%-40%。"
    else:
        signal_context = "directional_weak"
        direction_hint = side
        min_position_share_pct = strategy.weak_signal_min_position_share_pct
        max_position_share_pct = strategy.weak_signal_max_position_share_pct
        order_share_pct = strategy.weak_signal_order_share_pct
        reason = "信号初步成立，参考目标仓位区间可取 10%-20%。"

    if risk_stage == "observe":
        min_position_share_pct = 0.0
        max_position_share_pct = min(max_position_share_pct, strategy.observe_cap_position_share_pct)
        order_share_pct = min(order_share_pct, strategy.observe_cap_order_share_pct)
        reason = f"仓位已有回撤观察信号，建议把目标仓位压到 {_format_share_range(min_position_share_pct, max_position_share_pct)}。"
    elif risk_stage == "reduce":
        min_position_share_pct = 0.0
        max_position_share_pct = min(max_position_share_pct, strategy.reduce_cap_position_share_pct)
        order_share_pct = min(order_share_pct, strategy.reduce_cap_order_share_pct)
        reason = f"仓位进入收缩阶段，目标仓位应压到 {_format_share_range(min_position_share_pct, max_position_share_pct)}。"
    elif risk_stage == "exit":
        min_position_share_pct = 0.0
        max_position_share_pct = strategy.exit_cap_position_share_pct
        order_share_pct = strategy.exit_cap_order_share_pct
        reason = "仓位处于退出阶段，默认目标仓位为 0。"

    try:
        funding = abs(float(funding_rate)) if funding_rate is not None else 0.0
    except Exception:
        funding = 0.0
    if funding >= strategy.funding_hot_threshold:
        min_position_share_pct *= strategy.funding_hot_scale
        max_position_share_pct *= strategy.funding_hot_scale
        order_share_pct *= strategy.funding_hot_scale
        reason = f"资金费率偏热，建议下调目标仓位区间至 {_format_share_range(min_position_share_pct, max_position_share_pct)}。"

    min_position_share_pct = _round_share_pct(min_position_share_pct)
    max_position_share_pct = _round_share_pct(max_position_share_pct)
    if max_position_share_pct < min_position_share_pct:
        min_position_share_pct = max_position_share_pct
    order_share_pct = _round_share_pct(min(order_share_pct, max_position_share_pct))
    try:
        minimum_actionable_share_pct = float(item.get("minimum_actionable_share_pct_of_exposure_budget", 0.0) or 0.0)
    except Exception:
        minimum_actionable_share_pct = 0.0
    if minimum_actionable_share_pct > 0 and 0 < max_position_share_pct < minimum_actionable_share_pct:
        min_position_share_pct = 0.0
        max_position_share_pct = 0.0
        order_share_pct = 0.0
        reason = "当前账户规模下低于交易所最小下单额，默认目标仓位为 0。"
    elif 0 < min_position_share_pct < minimum_actionable_share_pct <= max_position_share_pct:
        min_position_share_pct = _round_share_pct(minimum_actionable_share_pct)
    anchor_position_share_pct = (
        _round_share_pct((min_position_share_pct + max_position_share_pct) / 2)
        if max_position_share_pct > 0
        else 0.0
    )
    return {
        "max_position_share_pct": anchor_position_share_pct,
        "max_order_share_pct": order_share_pct,
        "target_position_share_pct": anchor_position_share_pct,
        "target_position_share_min_pct": min_position_share_pct,
        "target_position_share_max_pct": max_position_share_pct,
        "target_position_share_range_pct": {
            "min": min_position_share_pct,
            "max": max_position_share_pct,
        },
        "reason": reason,
        "signal_context": signal_context,
        "signal_direction_hint": direction_hint,
        "price": snapshot_price,
        "funding_rate": funding_rate,
        "minimum_trade_notional_usd": item.get("minimum_trade_notional_usd"),
        "minimum_actionable_share_pct_of_exposure_budget": minimum_actionable_share_pct,
    }

def _recommended_limits_by_symbol(payload: dict[str, Any], strategy: StrategyConfig) -> dict[str, dict[str, Any]]:
    limits: dict[str, dict[str, Any]] = {}
    for item in payload.get("products", []):
        symbol = str(item.get("product_id", "")).upper()
        if not symbol:
            continue
        limits[symbol] = _perp_recommended_limits(item, strategy)
    return limits
