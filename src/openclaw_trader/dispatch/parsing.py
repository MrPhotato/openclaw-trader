from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from ..models import LlmTradeReviewDecision, LlmTradeReviewOrderDecision

@dataclass
class DispatchAction:
    kind: str
    deliver: bool
    reason: str
    message: str
    agent_id: str = "crypto-chief"
    state_mark_key: str | None = None

def _extract_first_payload_text(result: dict[str, object]) -> str:
    payload = result.get("payload") or {}
    if not isinstance(payload, dict):
        return ""
    result_payload = payload.get("result")
    if isinstance(result_payload, dict):
        payloads = result_payload.get("payloads") or []
    else:
        payloads = payload.get("payloads") or []
    if not isinstance(payloads, list) or not payloads:
        return ""
    first = payloads[0] or {}
    if not isinstance(first, dict):
        return ""
    return str(first.get("text") or "").strip()

def _extract_json_object(text: str) -> dict[str, object]:
    text = text.strip()
    if not text:
        raise ValueError("empty llm response")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("llm response does not contain json object")
        payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("llm response json is not an object")
    return payload

def _optional_decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None

def parse_trade_review_response(text: str) -> LlmTradeReviewDecision:
    payload = _extract_json_object(text)
    raw_orders = payload.get("orders")
    orders: list[LlmTradeReviewOrderDecision] = []
    if raw_orders is not None:
        if not isinstance(raw_orders, list):
            raise ValueError("trade review orders must be a list")
        for item in raw_orders:
            if not isinstance(item, dict):
                raise ValueError("trade review order entry must be an object")
            product_id = str(item.get("product_id", "")).strip().upper()
            if not product_id:
                raise ValueError("trade review order missing product_id")
            order_decision = str(item.get("decision", "observe")).strip().lower()
            if order_decision not in {"approve", "reject", "observe"}:
                raise ValueError(f"invalid trade review order decision: {order_decision}")
            try:
                order_size_scale = float(item.get("size_scale", 1.0))
            except Exception as exc:
                raise ValueError("invalid trade review order size_scale") from exc
            order_reason = str(item.get("reason", "")).strip()
            if not order_reason:
                raise ValueError(f"missing trade review order reason for {product_id}")
            exit_plan = str(item.get("exit_plan", "")).strip() or None
            orders.append(
                LlmTradeReviewOrderDecision(
                    product_id=product_id,
                    decision=order_decision,
                    size_scale=max(0.0, min(order_size_scale, 1.0)),
                    reason=order_reason,
                    stop_loss_price=_optional_decimal(item.get("stop_loss_price")),
                    take_profit_price=_optional_decimal(item.get("take_profit_price")),
                    exit_plan=exit_plan,
                )
            )
    decision = str(payload.get("decision", "")).strip().lower()
    if not decision:
        if any(item.decision == "approve" for item in orders):
            decision = "approve"
        elif any(item.decision == "observe" for item in orders):
            decision = "observe"
        else:
            decision = "reject"
    if decision not in {"approve", "reject", "observe"}:
        raise ValueError(f"invalid trade review decision: {decision}")
    try:
        size_scale = float(payload.get("size_scale", 1.0))
    except Exception as exc:
        raise ValueError("invalid trade review size_scale") from exc
    size_scale = max(0.0, min(size_scale, 1.0))
    reason = str(payload.get("reason", "")).strip()
    if not reason:
        if orders:
            reason = "batch_trade_review"
        else:
            raise ValueError("missing trade review reason")
    return LlmTradeReviewDecision(decision=decision, size_scale=size_scale, reason=reason, orders=orders)
