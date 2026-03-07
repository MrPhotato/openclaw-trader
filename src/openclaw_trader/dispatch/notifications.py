from __future__ import annotations

import json
from decimal import Decimal
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import RuntimeConfig
from ..models import AutopilotDecision, AutopilotPhase, EntryWorkflowMode, LlmTradeReviewDecision
from .parsing import DispatchAction, _extract_first_payload_text
from .prompts import STRATEGY_NOTIFY_PROMPT


def resolve_owner_main_agent(reply_to: str, *, registry_path: Path) -> str:
    if reply_to.startswith("user:") and registry_path.exists():
        try:
            payload = json.loads(registry_path.read_text())
            sender_id = reply_to.split(":", 1)[1]
            users = payload.get("users") if isinstance(payload, dict) else {}
            if isinstance(users, dict):
                record = users.get(sender_id)
                if isinstance(record, dict) and record.get("agentId"):
                    return str(record["agentId"])
        except Exception:
            pass
    return "main"


def notify_strategy_update(
    runner,
    runtime: RuntimeConfig,
    *,
    now: datetime,
    reason: str,
    resolve_owner_main_agent_fn,
    strategy_doc: dict[str, Any] | None = None,
) -> dict[str, object]:
    action = DispatchAction(
        kind="strategy_notify",
        deliver=False,
        reason=reason,
        message=STRATEGY_NOTIFY_PROMPT,
        agent_id=resolve_owner_main_agent_fn(runtime.dispatch.reply_to),
    )
    result = deliver_generated_message(
        runner,
        action=action,
        now=now,
        fallback_message=format_strategy_update_message(strategy_doc, reason=reason),
    )
    result["kind"] = action.kind
    result["deliver"] = True
    result["reason"] = action.reason
    return result


def should_emit_trade_event(
    decision: AutopilotDecision,
    trade_review: LlmTradeReviewDecision | None,
    approved_trade_plans: list[dict[str, object]],
    executed_trades: list[dict[str, object]],
    *,
    market_mode: str,
) -> bool:
    if market_mode != "perps":
        return False
    if decision.phase != AutopilotPhase.trade:
        return False
    if trade_review is None:
        return False
    if not approved_trade_plans:
        return False
    if decision.flow_mode == EntryWorkflowMode.auto:
        return bool(executed_trades)
    if executed_trades:
        return True
    if not (decision.notify_user or any(item["decision"].notify_user for item in approved_trade_plans)):
        return False
    return True


def _safe_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _format_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text


def _trade_amount_text(plan: dict[str, Any]) -> str:
    margin = _safe_decimal(plan.get("margin_usd"))
    action = str(plan.get("action") or "").lower()
    leverage = None
    if action in {"close", "reduce"}:
        leverage = _safe_decimal(plan.get("current_position_leverage"))
    if leverage is None:
        leverage = _safe_decimal(plan.get("execution_leverage") or plan.get("leverage"))
    notional = _safe_decimal(plan.get("notional_usd"))
    if margin is None and notional is not None and leverage is not None and leverage > 0:
        margin = notional / leverage
    margin_text = _format_decimal(margin)
    leverage_text = _format_decimal(leverage)
    if margin_text and leverage_text:
        return f"原始金额：{margin_text} USD\n杠杆：{leverage_text}x"
    if margin_text:
        return f"原始金额：{margin_text} USD"
    notional_text = _format_decimal(notional)
    if notional_text:
        return f"金额：{notional_text} USD"
    return "金额：未知"


def _exit_plan_text(review: dict[str, Any]) -> str | None:
    stop_loss = _format_decimal(_safe_decimal(review.get("stop_loss_price")))
    take_profit = _format_decimal(_safe_decimal(review.get("take_profit_price")))
    exit_plan = str(review.get("exit_plan") or "").strip()
    parts: list[str] = []
    if stop_loss or take_profit:
        stop_text = stop_loss or "-"
        take_text = take_profit or "-"
        parts.append(f"止损/止盈计划：止损价 {stop_text} / 止盈价 {take_text}")
    if exit_plan:
        parts.append(f"退出计划：{exit_plan}")
    return "\n".join(parts) if parts else None


def _action_title(plan: dict[str, Any], product_id: str) -> str:
    action = str(plan.get("action") or "").lower()
    side = str(plan.get("side") or "").lower()
    side_text = "多" if side == "long" else "空" if side == "short" else ""
    if action == "open":
        return f"🔵💰 已执行 {product_id} {side_text}".strip()
    if action == "add":
        return f"🔵💰 已加仓 {product_id} {side_text}".strip()
    if action == "reduce":
        return f"🔵💰 已减仓 {product_id} {side_text}".strip()
    if action == "close":
        return f"🔵💰 已平仓 {product_id} {side_text}".strip()
    if action == "flip":
        return f"🔵💰 已反手 {product_id} 至{side_text}".strip()
    return f"🔵💰 已处理 {product_id}".strip()


def format_trade_event_message(
    decision: AutopilotDecision,
    approved_trade_plans: list[dict[str, object]],
    executed_trades: list[dict[str, object]],
) -> str:
    if executed_trades:
        blocks: list[str] = []
        for item in executed_trades:
            plan = dict(item.get("approved_plan") or {})
            review = dict(item.get("review") or {})
            product_id = str(item.get("product_id") or decision.product_id)
            lines = [
                _action_title(plan, product_id),
                _trade_amount_text(plan),
            ]
            exit_plan = _exit_plan_text(review)
            if exit_plan:
                lines.append(exit_plan)
            reason = str(review.get("reason") or "").strip()
            if reason:
                lines.append(f"原因：{reason}")
            blocks.append("\n".join(lines))
        lines = []
        if len(executed_trades) > 1:
            lines.append(f"🔵💰 本轮共执行 {len(executed_trades)} 笔")
            lines.append("")
        lines.append("\n\n".join(blocks))
        return "\n".join(lines)
    if approved_trade_plans:
        item = approved_trade_plans[0]
        plan = dict(item.get("plan") or {})
        review = dict(item.get("review") or {})
        product_id = str(item.get("decision").product_id if item.get("decision") else decision.product_id)
        lines = [
            f"🔵👀 已通过 {product_id} 交易审核",
            _trade_amount_text(plan),
        ]
        reason = str(review.get("reason") or "").strip()
        if reason:
            lines.append(f"原因：{reason}")
        return "\n".join(lines)
    lines = [f"🔵👀 {decision.product_id} 先观察"]
    if decision.signal:
        lines.append(f"信号：{decision.signal.side.value} / 置信度 {decision.signal.confidence:.2f}")
    if decision.latest_news:
        lines.append(f"背景：{decision.latest_news[0].title}")
    lines.append(f"原因：{decision.reason}")
    return "\n".join(lines)


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        body = stripped[3:-3].strip()
        if "\n" in body:
            first_line, rest = body.split("\n", 1)
            if first_line.strip().lower() in {"json", "javascript", "js"}:
                return rest.strip()
        return body
    return stripped


def _looks_like_structured_message(text: str) -> bool:
    stripped = _strip_code_fence(text)
    if not stripped:
        return True
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            json.loads(stripped)
            return True
        except Exception:
            return False
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        try:
            json.loads(stripped[start : end + 1])
            return True
        except Exception:
            pass
    return False


def deliver_generated_message(
    runner,
    *,
    action: DispatchAction,
    now: datetime,
    fallback_message: str,
) -> dict[str, object]:
    generated_action = DispatchAction(
        kind=action.kind,
        deliver=False,
        reason=action.reason,
        message=action.message,
        agent_id=action.agent_id,
        state_mark_key=action.state_mark_key,
    )
    generated_result = runner.run(generated_action, now=now)
    generated_text = _extract_first_payload_text(generated_result) if generated_result.get("success") else ""
    message = generated_text
    used_fallback_text = False
    if _looks_like_structured_message(generated_text):
        message = fallback_message
        used_fallback_text = True
    delivery_result = runner.send_text(message)
    delivery_result["generated_result"] = generated_result
    delivery_result["generated_text"] = generated_text
    delivery_result["used_fallback_text"] = used_fallback_text
    delivery_result["text"] = message
    return delivery_result


def _format_strategy_symbol(item: dict[str, Any]) -> str:
    symbol = str(item.get("symbol") or "").strip().upper()
    if not symbol:
        return ""
    bias = str(item.get("bias") or "neutral").strip().lower()
    target = item.get("target_position_share_pct", item.get("max_position_share_pct", 0))
    target_text = _format_decimal(_safe_decimal(target)) or "0"
    return f"- {symbol}: {bias} {target_text}%"


def format_strategy_update_message(strategy_doc: dict[str, Any] | None, *, reason: str) -> str:
    strategy_doc = strategy_doc or {}
    version = strategy_doc.get("version")
    regime = str(strategy_doc.get("market_regime") or "unknown")
    risk_mode = str(strategy_doc.get("risk_mode") or "aggressive")
    summary = str(strategy_doc.get("summary") or "").strip()
    symbols = strategy_doc.get("symbols") if isinstance(strategy_doc.get("symbols"), list) else []
    symbol_lines = [_format_strategy_symbol(item) for item in symbols if isinstance(item, dict)]
    symbol_lines = [line for line in symbol_lines if line]
    lines = [
        "📊 策略更新",
        f"原因：{reason}",
        f"版本：v{version}" if version is not None else "版本：未记录",
        f"市场状态：{regime}",
        f"风险模式：{risk_mode}",
    ]
    if summary:
        lines.append(f"摘要：{summary}")
    if symbol_lines:
        lines.append("当前目标：")
        lines.extend(symbol_lines[:5])
    return "\n".join(lines)


def format_daily_report_message(
    *,
    now: datetime,
    decision: AutopilotDecision,
    strategy_doc: dict[str, Any] | None,
) -> str:
    strategy_doc = strategy_doc or {}
    local_now = now.strftime("%m/%d %H:%M")
    version = strategy_doc.get("version")
    regime = str(strategy_doc.get("market_regime") or "unknown")
    risk_mode = str(strategy_doc.get("risk_mode") or "aggressive")
    summary = str(strategy_doc.get("summary") or "").strip()
    lines = [
        f"📘 日报 | {local_now}",
        f"当前主状态：{decision.product_id} {decision.phase.value} / {decision.reason}",
        f"当前策略：v{version}" if version is not None else "当前策略：未记录",
        f"市场状态：{regime}",
        f"风险模式：{risk_mode}",
    ]
    if summary:
        lines.append(f"摘要：{summary}")
    if decision.signal:
        lines.append(f"信号：{decision.signal.side.value} / 置信度 {decision.signal.confidence:.2f}")
    return "\n".join(lines)
