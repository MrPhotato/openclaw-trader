from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .config import REPORT_DIR
from .engine import TraderEngine
from .perps.runtime import PerpSystemState, PerpSupervisor
from .models import AutopilotDecision, LlmTradeReviewDecision


DISPATCH_BRIEF_JSON = REPORT_DIR / "dispatch-brief.json"
DISPATCH_BRIEF_MD = REPORT_DIR / "dispatch-brief.md"
NEWS_BRIEF_JSON = REPORT_DIR / "news-brief.json"
PERP_NEWS_BRIEF_JSON = REPORT_DIR / "news-brief-perps.json"
PERP_NEWS_BRIEF_MD = REPORT_DIR / "news-brief-perps.md"


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


def _format_trade_amount(item: dict[str, Any]) -> str:
    margin = _safe_decimal(item.get("margin_usd"))
    leverage = _safe_decimal(item.get("execution_leverage") or item.get("leverage"))
    notional = _safe_decimal(item.get("notional_usd"))
    if margin is None and notional is not None and leverage is not None and leverage > 0:
        margin = notional / leverage
    parts: list[str] = []
    margin_text = _format_decimal(margin)
    leverage_text = _format_decimal(leverage)
    notional_text = _format_decimal(notional)
    if margin_text is not None:
        parts.append(f"原始金额={margin_text} USD")
    if leverage_text is not None and leverage is not None and leverage > 0:
        parts.append(f"杠杆={leverage_text}x")
    if not parts and notional_text is not None:
        parts.append(f"金额记录={notional_text} USD")
        parts.append("杠杆未知")
    return ", ".join(parts) if parts else "金额未知"


def _format_exit_plan(item: dict[str, Any]) -> str | None:
    stop_loss = _format_decimal(_safe_decimal(item.get("stop_loss_price")))
    take_profit = _format_decimal(_safe_decimal(item.get("take_profit_price")))
    exit_plan = str(item.get("exit_plan") or "").strip()
    parts: list[str] = []
    if stop_loss is not None:
        parts.append(f"止损价={stop_loss}")
    if take_profit is not None:
        parts.append(f"止盈价={take_profit}")
    if exit_plan:
        parts.append(f"退出计划={exit_plan}")
    return " | ".join(parts) if parts else None


def _load_news_summary(*, prefer_perps: bool = False) -> str:
    candidates = [PERP_NEWS_BRIEF_JSON, NEWS_BRIEF_JSON] if prefer_perps else [NEWS_BRIEF_JSON, PERP_NEWS_BRIEF_JSON]
    for path in candidates:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text())
            summary = str(payload.get("summary") or "").strip()
            if summary:
                return summary
        except Exception:
            continue
    return "暂无新闻摘要。"


def _news_summary_from_items(items: list[dict[str, Any]]) -> str:
    if not items:
        return "过去24小时无与永续交易直接相关的高价值新闻。"
    layers: dict[str, int] = {}
    for item in items:
        layer = str(item.get("layer", "unknown"))
        layers[layer] = layers.get(layer, 0) + 1
    ordered = []
    for layer in ("exchange-status", "exchange-announcement", "official-x", "macro", "regulation", "structured-news", "event-calendar"):
        count = layers.get(layer, 0)
        if count:
            ordered.append(f"{layer}:{count}")
    return "过去24小时永续相关新闻风向：" + ("，".join(ordered) if ordered else "较平静")


def write_perp_news_brief(supervisor: PerpSupervisor) -> dict[str, Any]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    items = [item.model_dump(mode="json") for item in supervisor.strategy_news(max_age_minutes=24 * 60, limit=20)]
    urgent_items = [item for item in items if str(item.get("severity", "")).lower() in {"medium", "high"}][:5]
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": _news_summary_from_items(items),
        "urgent_items": urgent_items,
        "recent_items": items[:10],
    }
    PERP_NEWS_BRIEF_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    lines = [
        f"生成时间：{payload['generated_at']}",
        payload["summary"],
        "",
        "重点新闻：",
    ]
    if urgent_items:
        lines.extend(f"- {item['title']}" for item in urgent_items)
    else:
        lines.append("- 无")
    PERP_NEWS_BRIEF_MD.write_text("\n".join(lines))
    return payload


def write_dispatch_brief(engine: TraderEngine, decision: AutopilotDecision, product_id: str | None = None) -> dict[str, Any]:
    product_id = product_id or decision.product_id
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    product = engine.ctx.client.get_product(product_id)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "product_id": product_id,
        "trigger": {
            "phase": decision.phase.value,
            "reason": decision.reason,
            "notify_user": decision.notify_user,
            "flow_mode": decision.flow_mode.value,
        },
        "market": {
            "price": str(product.price),
            "total_equity_usd": str(engine.total_equity_usd(product_id)),
            "current_position_quote_usd": str(engine.current_position_quote_usd(product_id)),
        },
        "signal": decision.signal.model_dump(mode="json") if decision.signal else None,
        "risk": decision.risk.model_dump(mode="json") if decision.risk else None,
        "panic": decision.panic.model_dump(mode="json") if decision.panic else None,
        "latest_news": [item.model_dump(mode="json") for item in decision.latest_news[:3]],
        "news_summary": _load_news_summary(),
    }
    DISPATCH_BRIEF_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    lines = [
        f"生成时间：{payload['generated_at']}",
        f"产品：{product_id}",
        f"触发：{payload['trigger']['phase']} / {payload['trigger']['reason']}",
        f"现价：{payload['market']['price']}",
        f"总权益：{payload['market']['total_equity_usd']} USDC",
        f"当前仓位（现货市值）：{payload['market']['current_position_quote_usd']} USDC",
        f"新闻摘要：{payload['news_summary']}",
    ]
    if payload["signal"]:
        lines.append(f"信号：{payload['signal']['side']} / 置信度 {payload['signal']['confidence']}")
        lines.append(f"理由：{payload['signal']['reason']}")
    if payload["panic"]:
        lines.append(
            "风控："
            f"阶段 {payload['panic']['position_risk_stage']} / "
            f"仓位回撤 {payload['panic']['position_drawdown_pct']}"
        )
    if payload["latest_news"]:
        lines.append("最近新闻：")
        lines.extend(f"- {item['title']}" for item in payload["latest_news"])
    DISPATCH_BRIEF_MD.write_text("\n".join(lines))
    return payload


def write_perp_dispatch_brief(
    supervisor: PerpSupervisor,
    system_state: PerpSystemState,
    *,
    transition_context: dict[str, Any] | None = None,
    trade_review: LlmTradeReviewDecision | dict[str, Any] | None = None,
    execution_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    portfolio = supervisor.portfolio()
    serialized_review = (
        trade_review.model_dump(mode="json")
        if isinstance(trade_review, LlmTradeReviewDecision)
        else trade_review
    )
    trade_candidates: list[dict[str, Any]] = []
    for decision in system_state.decisions:
        plan = ((decision.preview or {}).get("plan") if decision.preview else None) or None
        if decision.phase.value != "trade":
            continue
        if not plan:
            continue
        trade_candidates.append(
            {
                "product_id": decision.product_id,
                "notify_user": decision.notify_user,
                "reason": decision.reason,
                "signal": decision.signal.model_dump(mode="json") if decision.signal else None,
                "plan": plan,
            }
        )
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "market_mode": "perps",
        "trigger": {
            "phase": system_state.primary.phase.value,
            "reason": system_state.primary.reason,
            "notify_user": system_state.primary.notify_user,
            "flow_mode": system_state.primary.flow_mode.value,
        },
        "portfolio": portfolio.model_dump(mode="json"),
        "decisions": [decision.model_dump(mode="json") for decision in system_state.decisions],
        "trade_candidates": trade_candidates,
        "latest_news": [item.model_dump(mode="json") for item in system_state.latest_news[:5]],
        "news_summary": _load_news_summary(prefer_perps=True),
        "transition_context": transition_context,
        "trade_review": serialized_review,
        "execution_result": execution_result,
    }
    DISPATCH_BRIEF_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    lines = [
        f"生成时间：{payload['generated_at']}",
        f"触发：{payload['trigger']['phase']} / {payload['trigger']['reason']}",
        f"组合权益：{payload['portfolio']['total_equity_usd']} USD",
        f"可用权益：{payload['portfolio']['available_equity_usd']} USD",
        f"总敞口：{payload['portfolio']['total_exposure_usd']} USD",
        f"新闻摘要：{payload['news_summary']}",
        "",
    ]
    if transition_context:
        lines.extend(
            [
                "状态迁移：",
                (
                    f"- previous={transition_context.get('previous_phase')} / "
                    f"{transition_context.get('previous_reason')} / "
                    f"{transition_context.get('previous_product_id')}"
                ),
                (
                    f"- current={transition_context.get('current_phase')} / "
                    f"{transition_context.get('current_reason')} / "
                    f"{transition_context.get('current_product_id')}"
                ),
                f"- transition={transition_context.get('transition')}",
                f"- why_now_unblocked={transition_context.get('why_now_unblocked')}",
                "",
            ]
        )
    lines.extend(
        [
        "品种状态：",
        ]
    )
    for decision in system_state.decisions:
        signal = decision.signal.model_dump(mode="json") if decision.signal else {}
        risk = decision.risk.model_dump(mode="json") if decision.risk else {}
        lines.append(
            f"- {decision.product_id}: phase={decision.phase.value}, signal={signal.get('side')}, confidence={signal.get('confidence')}, risk={risk.get('reason')}"
        )
        if decision.signal:
            lines.append(f"  reason={decision.signal.reason}")
        if decision.panic:
            lines.append(f"  position_drawdown={decision.panic.position_drawdown_pct}, stage={decision.panic.position_risk_stage}")
    if trade_candidates:
        lines.extend(["", "Trade Candidates："])
        for item in trade_candidates:
            plan = item["plan"] or {}
            signal = item.get("signal") or {}
            lines.append(
                f"- {item['product_id']}: action={plan.get('action')}, side={plan.get('side')}, {_format_trade_amount(plan)}, signal={signal.get('side')}, confidence={signal.get('confidence')}"
            )
            lines.append(f"  reason={item['reason']}")
    if serialized_review:
        lines.extend(["", "LLM 审核：", f"- decision={serialized_review.get('decision')}", f"- reason={serialized_review.get('reason')}"])
        orders = serialized_review.get("orders") if isinstance(serialized_review, dict) else None
        if isinstance(orders, list) and orders:
            for item in orders:
                lines.append(
                    f"- {item.get('product_id')}: decision={item.get('decision')}, size_scale={item.get('size_scale')}, reason={item.get('reason')}"
                )
                exit_plan = _format_exit_plan(item)
                if exit_plan:
                    lines.append(f"  {exit_plan}")
        else:
            lines.append(f"- size_scale={serialized_review.get('size_scale')}")
    if execution_result:
        lines.extend(["", "执行结果："])
        items = execution_result.get("items") if isinstance(execution_result, dict) else None
        if isinstance(items, list) and items:
            for item in items:
                approved_plan = (item.get("approved_plan") or {}) if isinstance(item, dict) else {}
                lines.append(
                    f"- {item.get('product_id')}: success={item.get('success')}, action={approved_plan.get('action')}, {_format_trade_amount(approved_plan)}, error={item.get('error')}"
                )
                review = (item.get("review") or {}) if isinstance(item, dict) else {}
                exit_plan = _format_exit_plan(review)
                if exit_plan:
                    lines.append(f"  {exit_plan}")
        else:
            lines.append(f"- {json.dumps(execution_result, ensure_ascii=False)}")
    if payload["latest_news"]:
        lines.extend(["", "最近新闻："])
        lines.extend(f"- {item['title']}" for item in payload["latest_news"])
    DISPATCH_BRIEF_MD.write_text("\n".join(lines))
    return payload
