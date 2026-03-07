from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable

from ..models import AutopilotDecision, AutopilotPhase, LlmTradeReviewDecision


def trade_review_candidates(system_state) -> list[AutopilotDecision]:
    candidates: list[AutopilotDecision] = []
    action_priority = {
        "close": 0,
        "reduce": 1,
        "flip": 2,
        "open": 3,
        "add": 4,
    }
    for decision in system_state.decisions:
        plan = ((decision.preview or {}).get("plan") if decision.preview else None) or {}
        if decision.phase != AutopilotPhase.trade or not plan:
            continue
        candidates.append(decision)
    return sorted(
        candidates,
        key=lambda item: (
            action_priority.get(str((((item.preview or {}).get("plan") if item.preview else None) or {}).get("action", "")), 99),
            item.product_id,
        ),
    )


def scale_trade_plan(
    decision: AutopilotDecision,
    *,
    review_decision: str,
    size_scale: float,
    optional_decimal: Callable[[Any], Decimal | None],
) -> dict[str, Any] | None:
    plan = ((decision.preview or {}).get("plan") if decision.preview else None) or {}
    if not plan or decision.signal is None:
        return None
    if review_decision != "approve":
        return None
    action = str(plan.get("action", ""))
    notional_raw = plan.get("notional_usd")
    if notional_raw is None:
        return None
    original_notional = Decimal(str(notional_raw))
    original_margin = optional_decimal(plan.get("margin_usd"))
    execution_leverage = optional_decimal(plan.get("execution_leverage"))
    if original_margin is None and execution_leverage is not None and execution_leverage > 0:
        original_margin = original_notional / execution_leverage
    scaled_notional = original_notional * Decimal(str(size_scale))
    minimum_notional = Decimal(str(plan.get("minimum_trade_notional_usd", "0")))
    max_allowed = decision.risk.max_allowed_quote_usd if decision.risk and action in {"open", "add", "flip"} else None
    if max_allowed is not None:
        scaled_notional = min(scaled_notional, max_allowed)
    if scaled_notional <= 0:
        return None
    adjusted = dict(plan)
    if original_margin is not None and original_notional > 0:
        scaled_margin = (original_margin * (scaled_notional / original_notional)).quantize(Decimal("0.00000001"))
    else:
        scaled_margin = None
    if action == "close":
        if original_notional <= minimum_notional:
            adjusted["notional_usd"] = str(original_notional.quantize(Decimal("0.00000001")))
            if original_margin is not None:
                adjusted["margin_usd"] = str(original_margin.quantize(Decimal("0.00000001")))
            return adjusted
        if scaled_notional >= original_notional:
            adjusted["notional_usd"] = str(original_notional.quantize(Decimal("0.00000001")))
            if original_margin is not None:
                adjusted["margin_usd"] = str(original_margin.quantize(Decimal("0.00000001")))
            return adjusted
        if minimum_notional > 0 and scaled_notional < minimum_notional:
            return None
        adjusted["action"] = "reduce"
    elif minimum_notional > 0 and scaled_notional < minimum_notional:
        return None
    adjusted["notional_usd"] = str(scaled_notional.quantize(Decimal("0.00000001")))
    if scaled_margin is not None:
        adjusted["margin_usd"] = str(scaled_margin)
    return adjusted


def _optional_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _format_ratio_percent(value: Decimal | None) -> str | None:
    if value is None:
        return None
    percent = (value * Decimal("100")).quantize(Decimal("0.1"))
    text = format(percent.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _plan_action_summary(product_id: str, plan: dict[str, Any], *, effective_size_scale: Decimal | None) -> str:
    action = str(plan.get("action") or "").lower()
    side = str(plan.get("side") or "").lower()
    side_text = "多" if side == "long" else "空" if side == "short" else ""
    summary = {
        "open": f"开仓 {product_id} {side_text}".strip(),
        "add": f"加仓 {product_id} {side_text}".strip(),
        "reduce": f"减仓 {product_id} {side_text}".strip(),
        "close": f"全平 {product_id} {side_text}".strip(),
        "flip": f"反手 {product_id} 至{side_text}".strip(),
    }.get(action, f"处理 {product_id}".strip())
    ratio_text = _format_ratio_percent(effective_size_scale)
    if action != "close" and ratio_text and effective_size_scale is not None and effective_size_scale < Decimal("0.9999"):
        return f"按结构化审核执行：{summary}，本次执行约为原计划的 {ratio_text}%。"
    return f"按结构化审核执行：{summary}。"


def normalize_review_payload(
    decision: AutopilotDecision,
    *,
    review_payload: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    original_plan = ((decision.preview or {}).get("plan") if decision.preview else None) or {}
    original_notional = _optional_decimal(original_plan.get("notional_usd"))
    final_notional = _optional_decimal(plan.get("notional_usd"))
    effective_size_scale: Decimal | None = None
    if original_notional is not None and original_notional > 0 and final_notional is not None:
        effective_size_scale = final_notional / original_notional
    normalized = dict(review_payload)
    original_reason = str(normalized.get("reason") or "").strip()
    if original_reason:
        normalized["llm_reason"] = original_reason
    normalized["reason"] = _plan_action_summary(
        decision.product_id,
        plan,
        effective_size_scale=effective_size_scale,
    )
    normalized["effective_action"] = str(plan.get("action") or "")
    if effective_size_scale is not None:
        normalized["effective_size_scale"] = float(effective_size_scale)
    return normalized


def approved_trade_plans(
    system_state,
    trade_review: LlmTradeReviewDecision,
    *,
    scale_trade_plan_fn: Callable[..., dict[str, Any] | None],
) -> list[dict[str, Any]]:
    candidates = trade_review_candidates(system_state)
    if not candidates:
        return []
    by_product_id = {decision.product_id.upper(): decision for decision in candidates}
    approved: list[dict[str, Any]] = []
    if trade_review.orders:
        seen: set[str] = set()
        for item in trade_review.orders:
            product_id = item.product_id.upper()
            if product_id in seen:
                continue
            seen.add(product_id)
            decision = by_product_id.get(product_id)
            if decision is None:
                continue
            plan = scale_trade_plan_fn(
                decision,
                review_decision=item.decision,
                size_scale=item.size_scale,
            )
            if plan is None:
                continue
            review_payload = normalize_review_payload(
                decision,
                review_payload=item.model_dump(mode="json"),
                plan=plan,
            )
            approved.append(
                {
                    "product_id": decision.product_id,
                    "decision": decision,
                    "review": review_payload,
                    "plan": plan,
                }
            )
        return approved
    primary = system_state.primary
    if primary.phase != AutopilotPhase.trade:
        return []
    plan = scale_trade_plan_fn(
        primary,
        review_decision=trade_review.decision,
        size_scale=trade_review.size_scale,
    )
    if plan is None:
        return []
    review_payload = normalize_review_payload(
        primary,
        review_payload={
            "product_id": primary.product_id,
            "decision": trade_review.decision,
            "size_scale": trade_review.size_scale,
            "reason": trade_review.reason,
        },
        plan=plan,
    )
    approved.append(
        {
            "product_id": primary.product_id,
            "decision": primary,
            "review": review_payload,
            "plan": plan,
        }
    )
    return approved
