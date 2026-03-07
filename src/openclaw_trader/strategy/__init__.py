from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from typing import TYPE_CHECKING

from ..config import REPORT_DIR, RuntimeConfig, StrategyConfig
from ..engine import TraderEngine
from ..models import AutopilotDecision, AutopilotPhase, NewsItem, PositionRiskStage
from ..state import StateStore

if TYPE_CHECKING:
    from ..perps.runtime import PerpSupervisor

from .formatting import (
    _as_float,
    _format_amount_text,
    _format_decimal_text,
    _format_review_exit_text,
    _format_share_range,
    _normalize_strategy_symbol,
    _optional_decimal,
    _parse_iso_datetime,
    _round_metric,
    _round_share_pct,
    _safe_decimal,
)
from .history import (
    _append_jsonl,
    _curve_window_summary,
    _holding_curve_summary,
    _invalidator_set,
    _load_jsonl,
    _load_strategy_history,
    _position_origin_memory,
    _price_curve_memory,
    _recent_orders_memory,
    _strategy_alignment,
    _strategy_at_time,
    _strategy_change_summary,
    _strategy_symbol_map,
    _summarize_recent_strategy_changes,
    strategy_update_is_material,
)
from .inputs import _perp_recommended_limits, _recommended_limits_by_symbol
from .parser import parse_strategy_response
from .rewrite import (
    _normalize_scheduled_rechecks,
    clear_strategy_pending_regime_shift,
    current_strategy_schedule_slot,
    mark_strategy_regime_shift_rewrite,
    routine_refresh_due,
    scheduled_recheck_reason,
    strategy_due_today,
    strategy_rewrite_due_by_news,
    strategy_rewrite_reason,
)


STRATEGY_INPUT_JSON = REPORT_DIR / "strategy-input.json"
STRATEGY_INPUT_MD = REPORT_DIR / "strategy-input.md"
STRATEGY_MEMORY_JSON = REPORT_DIR / "strategy-memory.json"
STRATEGY_MEMORY_MD = REPORT_DIR / "strategy-memory.md"
STRATEGY_DAY_JSON = REPORT_DIR / "strategy-day.json"
STRATEGY_DAY_MD = REPORT_DIR / "strategy-day.md"
STRATEGY_HISTORY_JSONL = REPORT_DIR / "strategy-history.jsonl"
POSITION_JOURNAL_JSONL = REPORT_DIR / "position-journal.jsonl"
STRATEGY_CHANGE_LOG_JSONL = REPORT_DIR / "strategy-change-log.jsonl"

_EXCHANGE_STATUS_STRATEGY_REWRITE_KEYWORDS = (
    "intx",
    "international exchange",
    "international derivatives",
    "derivatives",
    "derivative",
    "perpetual",
    "perp",
    "futures",
    "future",
    "matching engine",
    "order book",
    "trade execution",
    "liquidation",
    "settlement",
)

STRATEGY_PENDING_REGIME_SHIFT_KEY = "strategy:pending_regime_shift"
STRATEGY_LAST_REGIME_SHIFT_REWRITE_AT_KEY = "strategy:last_regime_shift_rewrite_at"






































def append_strategy_change_log_entry(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    entry = _strategy_change_summary(previous, current)
    entry["summary_to"] = current.get("summary")
    entry["invalidators"] = current.get("invalidators") or []
    _append_jsonl(STRATEGY_CHANGE_LOG_JSONL, entry)
    return entry


def load_strategy_change_log_entries(limit: int = 5) -> list[dict[str, Any]]:
    return _load_jsonl(STRATEGY_CHANGE_LOG_JSONL, limit=limit)


def append_position_journal_entry(entry: dict[str, Any]) -> dict[str, Any]:
    payload = dict(entry)
    _append_jsonl(POSITION_JOURNAL_JSONL, payload)
    return payload


def load_position_journal_entries(limit: int = 10) -> list[dict[str, Any]]:
    return _load_jsonl(POSITION_JOURNAL_JSONL, limit=limit)
























def build_strategy_memory_perps(
    runtime: RuntimeConfig,
    supervisor: "PerpSupervisor",
    state: StateStore,
    *,
    market_items: list[dict[str, Any]],
    current_strategy: dict[str, Any] | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    history = _load_strategy_history(limit=8, path=STRATEGY_HISTORY_JSONL)
    recent_position_journal = load_position_journal_entries(limit=8)
    recent_strategy_change_log = load_strategy_change_log_entries(limit=5)
    recent_orders = _recent_orders_memory(
        state,
        exchange=runtime.perps.exchange,
        now=now,
        current_strategy=current_strategy,
    )
    positions: list[dict[str, Any]] = []
    price_curves: list[dict[str, Any]] = []
    for item in market_items:
        product_id = str(item.get("product_id", "")).upper()
        if not product_id:
            continue
        position = item.get("position") if isinstance(item.get("position"), dict) else None
        positions.append(
            _position_origin_memory(
                state,
                exchange=runtime.perps.exchange,
                product_id=product_id,
                position=position,
                history=history,
                current_strategy=current_strategy,
            )
        )
        coin = product_id.split("-")[0]
        current_price = _safe_decimal(item.get("price"), "0")
        curve_entry: dict[str, Any] = {"product_id": product_id}
        try:
            curve_entry["curves"] = _price_curve_memory(
                supervisor,
                coin=coin,
                current_price=current_price,
                position=position,
                now=now,
            )
        except Exception as exc:
            curve_entry["error"] = str(exc)
        price_curves.append(curve_entry)

    strategy_changes = _summarize_recent_strategy_changes(history)
    payload = {
        "generated_at": now.astimezone(UTC).isoformat(),
        "recent_orders": recent_orders,
        "recent_position_journal": recent_position_journal,
        "recent_strategy_change_log": recent_strategy_change_log,
        "current_position_origins": positions,
        "recent_strategy_changes": strategy_changes,
        "price_curves": price_curves,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    STRATEGY_MEMORY_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    lines = [
        f"生成时间：{payload['generated_at']}",
        "",
        "当前仓位来历：",
    ]
    if positions:
        for item in positions:
            if not item.get("has_position"):
                lines.append(f"- {item['product_id']}: 当前无仓位")
                continue
            lines.append(
                f"- {item['product_id']}: {item.get('side')} | {_format_amount_text(notional_usd=item.get('notional_usd'), leverage=item.get('leverage'), margin_usd=item.get('margin_used_usd'))} @ {item.get('entry_price')} | opened_at={item.get('opened_at')} | 对当前战略={item.get('alignment_with_current_strategy')}"
            )
            if item.get("strategy_version_at_open") is not None:
                lines.append(
                    f"  开仓时战略：v{item.get('strategy_version_at_open')} / {item.get('strategy_reason_at_open')}"
                )
            if item.get("latest_fill"):
                latest_fill = item["latest_fill"]
                lines.append(
                    f"  最近相关成交：{latest_fill.get('executed_at')} | {latest_fill.get('action')} {latest_fill.get('side')} | {_format_amount_text(notional_usd=latest_fill.get('notional_usd'), leverage=latest_fill.get('leverage'))}"
                )
    else:
        lines.append("- 无")

    lines.extend(["", "最近订单摘要："])
    if recent_orders["orders"]:
        lines.append(
            f"- 窗口：{recent_orders['window_start']} -> {recent_orders['window_end']} | 共 {recent_orders['count']} 笔 | realized_pnl={recent_orders['total_realized_pnl_usd']} USD | commission={recent_orders['total_commission_usd']} USD"
        )
        for item in recent_orders["orders"][:8]:
            lines.append(
                f"- {item.get('executed_at')} | {item.get('product_id')} | {item.get('action')} {item.get('side')} | {_format_amount_text(notional_usd=item.get('notional_usd'), leverage=item.get('leverage'))} @ {item.get('price')}"
            )
    else:
        lines.append("- 当前窗口内无成交")

    lines.extend(["", "最近调仓日志："])
    if recent_position_journal:
        for item in recent_position_journal:
            lines.append(
                f"- {item.get('journaled_at')} | {item.get('product_id')} | success={item.get('success')} | plan={((item.get('approved_plan') or {}).get('action'))} {((item.get('approved_plan') or {}).get('side'))} | {_format_amount_text(notional_usd=((item.get('approved_plan') or {}).get('notional_usd')), leverage=((item.get('approved_plan') or {}).get('execution_leverage')), margin_usd=((item.get('approved_plan') or {}).get('margin_usd')))} | strategy=v{item.get('strategy_version')}"
            )
            lines.append(
                "  before="
                f"{((item.get('before_position') or {}).get('side'))}/"
                f"{_format_amount_text(notional_usd=((item.get('before_position') or {}).get('notional_usd')), leverage=((item.get('before_position') or {}).get('leverage')), margin_usd=((item.get('before_position') or {}).get('margin_used_usd')))}"
                " -> after="
                f"{((item.get('after_position') or {}).get('side'))}/"
                f"{_format_amount_text(notional_usd=((item.get('after_position') or {}).get('notional_usd')), leverage=((item.get('after_position') or {}).get('leverage')), margin_usd=((item.get('after_position') or {}).get('margin_used_usd')))}"
                f" | runtime={item.get('decision_reason')} | review={item.get('review_reason')}"
            )
            exit_text = _format_review_exit_text(item.get("review"))
            if exit_text:
                lines.append(f"  {exit_text}")
    else:
        lines.append("- 暂无调仓 journal")

    lines.extend(["", "最近战略变更日志："])
    if recent_strategy_change_log:
        for item in recent_strategy_change_log:
            lines.append(
                f"- {item.get('journaled_at')} | v{item.get('from_version', '-') } -> v{item.get('to_version', '-') } | {item.get('change_reason')}"
            )
            lines.append(
                f"  market {item.get('market_regime_from')} -> {item.get('market_regime_to')} | risk {item.get('risk_mode_from')} -> {item.get('risk_mode_to')} | summary={item.get('summary_to')}"
            )
    else:
        lines.append("- 暂无 strategy-change-log")

    lines.extend(["", "最近战略变化："])
    if strategy_changes:
        for item in strategy_changes:
            lines.append(
                f"- v{item.get('from_version', '-') } -> v{item.get('to_version', '-') } | {item.get('change_reason')} | market {item.get('market_regime_from')} -> {item.get('market_regime_to')} | risk {item.get('risk_mode_from')} -> {item.get('risk_mode_to')}"
            )
            for changed in item.get("changed_symbols", [])[:5]:
                lines.append(
                    f"  {changed.get('symbol')}: bias {changed.get('bias_from')} -> {changed.get('bias_to')} | pos {changed.get('max_position_share_pct_from')}% -> {changed.get('max_position_share_pct_to')}%"
                )
    else:
        lines.append("- 无历史 strategy change")

    lines.extend(["", "价格曲线摘要："])
    if price_curves:
        for item in price_curves:
            lines.append(f"- {item.get('product_id')}:")
            if item.get("error"):
                lines.append(f"  curve_error={item['error']}")
                continue
            curves = item.get("curves") or {}
            for period in curves.get("short_term", []) + curves.get("medium_term", []):
                lines.append(
                    f"  {period.get('label')}: return={period.get('return_pct')}%, current_vs_high={period.get('current_vs_high_pct')}%, current_vs_low={period.get('current_vs_low_pct')}%"
                )
            holding = curves.get("holding_period")
            if holding:
                lines.append(
                    f"  持仓期: side={holding.get('position_side')} | since_entry={holding.get('price_change_since_entry_pct')}% | max_favorable={holding.get('max_favorable_move_pct')}% | max_adverse={holding.get('max_adverse_move_pct')}%"
                )
            else:
                lines.append("  持仓期: 当前无仓位")
    else:
        lines.append("- 无")

    STRATEGY_MEMORY_MD.write_text("\n".join(lines))
    return payload


def build_strategy_input(
    runtime: RuntimeConfig,
    engine: TraderEngine,
    state: StateStore,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    strategy_cfg = runtime.strategy
    products = strategy_cfg.track_products or [runtime.app.primary_product]
    market_items: list[dict[str, Any]] = []
    for product_id in products:
        signal, risk = engine.evaluate_signal(product_id)
        panic = engine.evaluate_emergency_exit(product_id)
        snapshot = engine.market_snapshot(product_id)
        market_items.append(
            {
                "product_id": product_id,
                "price": str(snapshot.product.price),
                "signal": signal.model_dump(mode="json"),
                "risk": risk.model_dump(mode="json"),
                "panic": panic.model_dump(mode="json"),
            }
        )

    news_items = engine.recent_news(max_age_minutes=24 * 60, limit=20)
    recent_news = [item.model_dump(mode="json") for item in news_items[:10]]
    current = load_current_strategy()
    payload = {
        "generated_at": now.astimezone(UTC).isoformat(),
        "products": market_items,
        "recent_news": recent_news,
        "current_strategy": current,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    STRATEGY_INPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    lines = [
        f"生成时间：{payload['generated_at']}",
        "",
        "跟踪产品：",
    ]
    for item in market_items:
        signal = item["signal"]
        risk = item["risk"]
        lines.extend(
            [
                f"- {item['product_id']}: price={item['price']}, signal={signal['side']}, confidence={signal['confidence']:.2f}",
                f"  reason={signal['reason']}",
                f"  risk={risk['reason']}, approved={risk['approved']}",
            ]
        )
    lines.extend(["", "最近新闻："])
    if recent_news:
        for item in recent_news[:8]:
            published = item.get("published_at") or "-"
            lines.append(f"- [{item['layer']}/{item['severity']}] {item['title']} ({published})")
    else:
        lines.append("- 无")
    if current:
        lines.extend(
            [
                "",
                "当前生效战略：",
                f"- version={current.get('version')}",
                f"- market_regime={current.get('market_regime')}",
                f"- risk_mode={current.get('risk_mode')}",
                f"- summary={current.get('summary')}",
            ]
        )
    STRATEGY_INPUT_MD.write_text("\n".join(lines))
    return payload






def load_current_strategy(path: Path | None = None) -> dict[str, Any] | None:
    path = path or STRATEGY_DAY_JSON
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None










def save_strategy_doc(payload: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    current = load_current_strategy() or {}
    version = int(current.get("version", 0)) + 1
    document = dict(payload)
    document["version"] = version
    document["updated_at"] = now.astimezone(UTC).isoformat()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    STRATEGY_DAY_JSON.write_text(json.dumps(document, ensure_ascii=False, indent=2))

    lines = [
        f"版本：{version}",
        f"日期：{document.get('strategy_date', '-')}",
        f"更新时间：{document['updated_at']}",
        f"原因：{document.get('change_reason', '-')}",
        f"市场：{document.get('market_regime', '-')}",
        f"风险：{document.get('risk_mode', '-')}",
        f"软杠杆下限：{document.get('soft_min_leverage', 1)}x",
        f"软杠杆上限：{document.get('soft_max_leverage', '-') }x",
        (
            f"全局单笔硬上限：{document.get('global_max_order_share_pct')}%"
            if document.get("global_max_order_share_pct") is not None
            else "全局单笔硬上限：-"
        ),
        f"摘要：{document.get('summary', '-')}",
        "",
        "品种策略：",
    ]
    for item in document.get("symbols", []):
        lines.append(
            f"- {item.get('symbol', '-')} | bias={item.get('bias', '-')} | target_position_share={item.get('max_position_share_pct', item.get('max_position_pct', 0))}% | thesis={item.get('thesis', '-')}"
        )
    invalidators = document.get("invalidators", [])
    lines.extend(["", "失效条件："])
    if invalidators:
        lines.extend(f"- {item}" for item in invalidators)
    else:
        lines.append("- 无")
    watchlist = document.get("watchlist_suggestions") or {}
    if watchlist.get("add") or watchlist.get("remove") or watchlist.get("reason"):
        lines.extend(["", "跟踪范围建议："])
        if watchlist.get("add"):
            lines.append(f"- 建议新增：{', '.join(watchlist['add'])}")
        if watchlist.get("remove"):
            lines.append(f"- 建议移除：{', '.join(watchlist['remove'])}")
        if watchlist.get("reason"):
            lines.append(f"- 原因：{watchlist['reason']}")
    scheduled_rechecks = document.get("scheduled_rechecks") or []
    if scheduled_rechecks:
        lines.extend(["", "预约复盘："])
        for item in scheduled_rechecks:
            lines.append(
                f"- {item.get('run_at', '-')} | event={item.get('event_at', '-')} | {item.get('reason', '-')}"
            )
    STRATEGY_DAY_MD.write_text("\n".join(lines))
    with STRATEGY_HISTORY_JSONL.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(document, ensure_ascii=False) + "\n")
    append_strategy_change_log_entry(current if current else None, document)
    return document






















def build_strategy_input_perps(
    runtime: RuntimeConfig,
    supervisor: PerpSupervisor,
    state: StateStore,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    coins = runtime.perps.coins or [runtime.perps.coin]
    market_items: list[dict[str, Any]] = []
    portfolio = supervisor.portfolio()
    hard_total_exposure_pct = min(max(runtime.perps.max_total_exposure_pct_of_equity, 0.0), 100.0)
    hard_min_leverage = 1.0
    hard_max_leverage = max(runtime.perps.max_leverage, hard_min_leverage)
    hard_margin_budget = portfolio.total_equity_usd * Decimal(str(hard_total_exposure_pct / 100))
    hard_notional_budget = hard_margin_budget * Decimal(str(hard_max_leverage))
    for coin in coins:
        signal, risk = supervisor.evaluate_signal(coin)
        panic = supervisor.evaluate_emergency_exit(coin)
        snapshot = supervisor.engine.snapshot(coin)
        account = supervisor.engine.account(coin)
        try:
            model_status = supervisor.model_status(coin)
        except Exception as exc:
            model_status = {
                "coin": coin.upper(),
                "trained_at": None,
                "training_rows": 0,
                "validation_accuracy": 0.0,
                "validation_macro_f1": 0.0,
                "feature_names": [],
                "regime_state_map": {},
                "error": str(exc),
            }
        market_items.append(
            {
                "product_id": f"{coin.upper()}-PERP",
                "price": str(snapshot.mark_price),
                "minimum_trade_notional_usd": str(supervisor.engine.minimum_trade_notional_usd(coin)),
                "minimum_actionable_share_pct_of_exposure_budget": (
                    float(
                        supervisor.engine.minimum_trade_notional_usd(coin)
                        / max(
                            hard_notional_budget,
                            Decimal("0.00000001"),
                        )
                        * Decimal("100")
                    )
                    if hard_notional_budget > 0
                    else 0.0
                ),
                "funding_rate": str(snapshot.funding_rate) if snapshot.funding_rate is not None else None,
                "open_interest": str(snapshot.open_interest) if snapshot.open_interest is not None else None,
                "regime": signal.metadata.get("regime"),
                "regime_confidence": signal.metadata.get("regime_confidence"),
                "model_status": model_status,
                "signal": signal.model_dump(mode="json"),
                "risk": risk.model_dump(mode="json"),
                "panic": panic.model_dump(mode="json"),
                "position": account.position.model_dump(mode="json") if account.position else None,
            }
        )

    news_items = supervisor.strategy_news(max_age_minutes=24 * 60, limit=20)
    recent_news = [item.model_dump(mode="json") for item in news_items[:10]]
    current = load_current_strategy()
    build_strategy_memory_perps(
        runtime,
        supervisor,
        state,
        market_items=market_items,
        current_strategy=current,
        now=now,
    )
    payload = {
        "generated_at": now.astimezone(UTC).isoformat(),
        "market_mode": "perps",
        "portfolio": portfolio.model_dump(mode="json"),
        "hard_limits": {
            "max_total_exposure_pct_of_equity": hard_total_exposure_pct,
            "max_order_share_pct_of_exposure_budget": runtime.perps.max_order_share_pct_of_exposure_budget,
            "min_leverage": hard_min_leverage,
            "max_leverage": hard_max_leverage,
        },
        "tracked_products": [coin.upper() for coin in coins],
        "exposure_budget_usd": str(hard_margin_budget),
        "notional_budget_usd": str(hard_notional_budget),
        "products": market_items,
        "recommended_limits": {
            **_recommended_limits_by_symbol({"products": market_items}, runtime.strategy),
            "__meta__": {
                "hard_total_exposure_pct": hard_total_exposure_pct,
                "hard_max_order_share_pct": runtime.perps.max_order_share_pct_of_exposure_budget,
                "hard_min_leverage": hard_min_leverage,
                "hard_max_leverage": hard_max_leverage,
                "portfolio_total_equity_usd": float(portfolio.total_equity_usd),
            },
        },
        "recent_news": recent_news,
        "current_strategy": current,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    STRATEGY_INPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    lines = [
        f"生成时间：{payload['generated_at']}",
        f"组合权益：{payload['portfolio']['total_equity_usd']} USD",
        f"可用权益：{payload['portfolio']['available_equity_usd']} USD",
        f"总敞口：{payload['portfolio']['total_exposure_usd']} USD",
        f"敞口预算：{payload['exposure_budget_usd']} USD",
        f"名义仓位预算（按硬杠杆）：{payload['notional_budget_usd']} USD",
        f"硬总敞口上限：{payload['hard_limits']['max_total_exposure_pct_of_equity']}%",
        f"硬单笔上限：{payload['hard_limits']['max_order_share_pct_of_exposure_budget']}%",
        f"硬杠杆下限：{payload['hard_limits']['min_leverage']}x",
        f"硬杠杆上限：{payload['hard_limits']['max_leverage']}x",
        f"当前跟踪范围：{', '.join(payload['tracked_products'])}",
        "补充记忆：同时参考 strategy-memory.md（仓位来历、最近订单、战略变化、价格曲线）。",
        "",
        "跟踪品种：",
    ]
    for item in market_items:
        signal = item["signal"]
        risk = item["risk"]
        rec = payload["recommended_limits"].get(item["product_id"], {})
        lines.extend(
            [
                f"- {item['product_id']}: price={item['price']}, funding={item.get('funding_rate')}, oi={item.get('open_interest')}, regime={item.get('regime')}({item.get('regime_confidence')})",
                f"  signal={signal['side']}, confidence={signal['confidence']:.2f}, reason={signal['reason']}",
                f"  signal_context={rec.get('signal_context')}, direction_hint={rec.get('signal_direction_hint')}",
                f"  risk={risk['reason']}, approved={risk['approved']}",
                f"  model=source {signal.get('metadata', {}).get('signal_source', 'unknown')} / rows {item['model_status']['training_rows']} / val_acc {item['model_status']['validation_accuracy']:.3f} / val_f1 {item['model_status']['validation_macro_f1']:.3f}",
                f"  minimum_trade_notional_usd={item.get('minimum_trade_notional_usd')} / minimum_actionable_share_pct={item.get('minimum_actionable_share_pct_of_exposure_budget'):.2f}%",
                f"  recommended_target_range={_format_share_range(float((rec.get('target_position_share_range_pct') or {}).get('min', rec.get('target_position_share_min_pct', rec.get('target_position_share_pct', rec.get('max_position_share_pct', 0.0))))), float((rec.get('target_position_share_range_pct') or {}).get('max', rec.get('target_position_share_max_pct', rec.get('target_position_share_pct', rec.get('max_position_share_pct', 0.0))))))} / global_order_cap={payload['hard_limits']['max_order_share_pct_of_exposure_budget']}% ({rec.get('reason')})",
            ]
        )
        model_error = signal.get("metadata", {}).get("model_error")
        if model_error:
            lines.append(f"  model_error={model_error}")
    lines.extend(["", "最近新闻："])
    if recent_news:
        for item in recent_news[:8]:
            published = item.get("published_at") or "-"
            lines.append(f"- [{item['layer']}/{item['severity']}] {item['title']} ({published})")
    else:
        lines.append("- 无")
    if current:
        lines.extend(
            [
                "",
                "当前生效战略：",
                f"- version={current.get('version')}",
                f"- market_regime={current.get('market_regime')}",
                f"- risk_mode={current.get('risk_mode')}",
                f"- soft_min_leverage={current.get('soft_min_leverage', 1)}",
                f"- soft_max_leverage={current.get('soft_max_leverage')}",
                f"- summary={current.get('summary')}",
            ]
        )
    STRATEGY_INPUT_MD.write_text("\n".join(lines))
    return payload
