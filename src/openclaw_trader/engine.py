from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
import re
from typing import Any

from .coinbase import CoinbaseAdvancedClient
from .config import RuntimeConfig
from .models import AutopilotDecision, AutopilotPhase, Balance, EmergencyExitDecision, MarketSnapshot, NewsItem, OrderResult, PositionRiskStage
from .news.monitor import sync_news
from .risk import evaluate_manual_buy, evaluate_signal, classify_position_drawdown
from .signals.simple_btc import generate_btc_trend_signal
from .state import StateStore


@dataclass
class EngineContext:
    runtime: RuntimeConfig
    client: CoinbaseAdvancedClient
    state: StateStore


class TraderEngine:
    def __init__(self, ctx: EngineContext):
        self.ctx = ctx

    def recent_news(self, max_age_minutes: int = 24 * 60, limit: int = 50) -> list[NewsItem]:
        sync_news(self.ctx.runtime.news, self.ctx.state)
        return self.ctx.state.list_recent_news(max_age_minutes=max_age_minutes, limit=limit)

    def balances(self) -> list[Balance]:
        return self.ctx.client.list_accounts()

    def quote_balance(self, product_id: str | None = None) -> Balance | None:
        product_id = product_id or self.ctx.runtime.app.primary_product
        quote_currency = product_id.split("-")[1]
        for balance in self.balances():
            if balance.currency == quote_currency:
                return balance
        return None

    def base_balance(self, product_id: str | None = None) -> Balance | None:
        product_id = product_id or self.ctx.runtime.app.primary_product
        base_currency = product_id.split("-")[0]
        for balance in self.balances():
            if balance.currency == base_currency:
                return balance
        return None

    def usd_balance(self) -> Balance | None:
        return self.quote_balance(self.ctx.runtime.app.primary_product)

    def current_position_quote_usd(self, product_id: str | None = None) -> Decimal:
        product_id = product_id or self.ctx.runtime.app.primary_product
        base_currency = product_id.split("-")[0]
        product = self.ctx.client.get_product(product_id)
        base_units = Decimal("0")
        for balance in self.balances():
            if balance.currency == base_currency:
                base_units = balance.available + balance.hold
                break
        return (base_units * product.price).quantize(Decimal("0.00000001"))

    def total_equity_usd(self, product_id: str | None = None) -> Decimal:
        product_id = product_id or self.ctx.runtime.app.primary_product
        total = Decimal("0")
        for balance in self.balances():
            amount = balance.available + balance.hold
            if amount <= 0:
                continue
            if balance.currency in {"USD", "USDC"}:
                total += amount
        total += self.current_position_quote_usd(product_id)
        return total.quantize(Decimal("0.00000001"))

    def position_drawdown_state(self, product_id: str | None = None) -> dict[str, Any]:
        product_id = product_id or self.ctx.runtime.app.primary_product
        base_balance = self.base_balance(product_id)
        base_units = (base_balance.available + base_balance.hold) if base_balance else Decimal("0")
        current_quote = self.current_position_quote_usd(product_id)
        state_key = f"position-risk:{product_id}"
        if base_units <= 0 or current_quote <= 0:
            self.ctx.state.set_value(
                state_key,
                json.dumps(
                    {
                        "product_id": product_id,
                        "base_units": "0",
                        "peak_quote_usd": "0",
                        "drawdown_pct": 0.0,
                        "stage": PositionRiskStage.normal.value,
                    }
                ),
            )
            return {
                "product_id": product_id,
                "base_units": base_units,
                "peak_quote_usd": Decimal("0"),
                "drawdown_pct": 0.0,
                "stage": PositionRiskStage.normal,
            }
        raw = self.ctx.state.get_value(state_key)
        stored_units = Decimal("0")
        peak_quote = current_quote
        if raw:
            try:
                payload = json.loads(raw)
                stored_units = Decimal(str(payload.get("base_units", "0")))
                peak_quote = Decimal(str(payload.get("peak_quote_usd", str(current_quote))))
            except Exception:
                stored_units = Decimal("0")
                peak_quote = current_quote
        quantity_changed = stored_units <= 0 or abs(base_units - stored_units) > Decimal("0.00000001")
        if quantity_changed:
            peak_quote = current_quote
        else:
            peak_quote = max(peak_quote, current_quote)
        drawdown_pct = float(((peak_quote - current_quote) / peak_quote) * Decimal("100")) if peak_quote > 0 else 0.0
        stage = classify_position_drawdown(drawdown_pct, self.ctx.runtime.risk)
        self.ctx.state.set_value(
            state_key,
            json.dumps(
                {
                    "product_id": product_id,
                    "base_units": str(base_units),
                    "peak_quote_usd": str(peak_quote),
                    "drawdown_pct": drawdown_pct,
                    "stage": stage.value,
                }
            ),
        )
        return {
            "product_id": product_id,
            "base_units": base_units,
            "peak_quote_usd": peak_quote,
            "drawdown_pct": drawdown_pct,
            "stage": stage,
        }

    def daily_equity_baseline_usd(self, product_id: str | None = None) -> Decimal:
        product_id = product_id or self.ctx.runtime.app.primary_product
        current_equity = self.total_equity_usd(product_id)
        trading_day = datetime.now(timezone.utc).date().isoformat()
        baseline = self.ctx.state.get_or_create_daily_equity_baseline(trading_day, str(current_equity))
        return Decimal(str(baseline))

    def evaluate_emergency_exit(self, product_id: str | None = None) -> EmergencyExitDecision:
        product_id = product_id or self.ctx.runtime.app.primary_product
        current_position_quote = self.current_position_quote_usd(product_id)
        total_equity = self.total_equity_usd(product_id)
        baseline = self.daily_equity_baseline_usd(product_id)
        drawdown_pct = float(((baseline - total_equity) / baseline) * Decimal("100")) if baseline > 0 else 0.0
        position_risk = self.position_drawdown_state(product_id)

        triggers: list[str] = []
        latest_exchange_status_title = None
        latest_exchange_status_severity = None

        if self.ctx.runtime.risk.emergency_exit_enabled and position_risk["stage"] == PositionRiskStage.exit:
            triggers.append("position_drawdown_exit")

        news_items = self.recent_news(limit=20)
        for item in news_items:
            if item.source == "coinbase-status":
                latest_exchange_status_title = item.title
                latest_exchange_status_severity = item.severity
                if self.ctx.runtime.risk.emergency_exit_enabled and self.ctx.runtime.risk.emergency_exit_on_exchange_status and item.severity == "high":
                    triggers.append("exchange_status_high_severity")
                break

        if current_position_quote <= 0:
            return EmergencyExitDecision(
                should_exit=False,
                reason="no_open_position",
                triggers=[],
                total_equity_usd=total_equity,
                daily_equity_baseline_usd=baseline,
                daily_drawdown_pct=drawdown_pct,
                current_position_quote_usd=current_position_quote,
                position_peak_quote_usd=position_risk["peak_quote_usd"],
                position_drawdown_pct=position_risk["drawdown_pct"],
                position_risk_stage=position_risk["stage"],
                latest_exchange_status_title=latest_exchange_status_title,
                latest_exchange_status_severity=latest_exchange_status_severity,
            )

        should_exit = bool(triggers)
        reason = "approved_emergency_exit" if should_exit else "no_hard_exit_trigger"
        return EmergencyExitDecision(
            should_exit=should_exit,
            reason=reason,
            triggers=triggers,
            total_equity_usd=total_equity,
            daily_equity_baseline_usd=baseline,
            daily_drawdown_pct=drawdown_pct,
            current_position_quote_usd=current_position_quote,
            position_peak_quote_usd=position_risk["peak_quote_usd"],
            position_drawdown_pct=position_risk["drawdown_pct"],
            position_risk_stage=position_risk["stage"],
            latest_exchange_status_title=latest_exchange_status_title,
            latest_exchange_status_severity=latest_exchange_status_severity,
        )

    def _is_fresh_news(self, item: NewsItem, max_age_minutes: int) -> bool:
        if item.published_at is None:
            return False
        published_at = item.published_at
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - published_at <= timedelta(minutes=max_age_minutes)

    def _is_relevant_news(self, item: NewsItem) -> bool:
        keywords = [keyword.lower() for keyword in self.ctx.runtime.workflow.news_keywords]
        haystack = f"{item.title} {item.summary or ''}".lower()
        if any(re.search(rf"\b{re.escape(keyword)}\b", haystack) for keyword in keywords):
            return True
        high_context_layers = {"macro", "regulation", "exchange-announcement", "event-calendar"}
        if item.layer in high_context_layers and item.severity in {"medium", "high"}:
            return True
        high_context_tags = {"macro", "regulation", "rates", "policy", "event-calendar"}
        if any(tag.lower() in high_context_tags for tag in item.tags) and item.severity in {"medium", "high"}:
            return True
        return False

    def _notification_fingerprint(self, *parts: object) -> str:
        joined = "|".join("" if part is None else str(part) for part in parts)
        return sha256(joined.encode("utf-8")).hexdigest()

    def _display_symbol(self, product_id: str) -> str:
        return product_id.split("-")[0]

    def _format_pct(self, value: float | None, decimals: int = 1, signed: bool = False) -> str:
        if value is None:
            return "-"
        fmt = f"{{:{'+' if signed else ''}.{decimals}f}}%"
        return fmt.format(value)

    def _panic_trigger_text(self, panic: EmergencyExitDecision) -> str:
        if "position_drawdown_exit" in panic.triggers:
            return f"仓位回撤达到 {self._format_pct(panic.position_drawdown_pct, 1)}"
        if "exchange_status_high_severity" in panic.triggers:
            return "交易所高危状态"
        if panic.triggers:
            return panic.triggers[0]
        return panic.reason

    def autopilot_check(self, product_id: str | None = None) -> AutopilotDecision:
        product_id = product_id or self.ctx.runtime.app.primary_product
        workflow = self.ctx.runtime.workflow
        news_items = self.recent_news(limit=20)
        signal, risk = self.evaluate_signal(product_id)
        panic = self.evaluate_emergency_exit(product_id)

        latest_status = next((item for item in news_items if item.source == "coinbase-status"), None)
        latest_relevant_news = next(
            (
                item
                for item in news_items
                if item.source != "coinbase-status"
                and self._is_fresh_news(item, workflow.fresh_news_minutes)
                and self._is_relevant_news(item)
            ),
            None,
        )

        if panic.position_risk_stage == PositionRiskStage.reduce:
            fingerprint = self._notification_fingerprint(
                "position-reduce",
                product_id,
                round(panic.position_drawdown_pct or 0.0, 2),
            )
            notify_user = self.ctx.state.should_emit_notification(
                f"autopilot:{product_id}:position-reduce",
                fingerprint,
                workflow.panic_notify_cooldown_minutes,
            )
            return AutopilotDecision(
                phase=AutopilotPhase.observe,
                notify_user=notify_user,
                reason="position_drawdown_requires_risk_reduction",
                product_id=product_id,
                flow_mode=workflow.entry_mode,
                signal=signal,
                risk=risk,
                panic=panic,
                latest_news=[item for item in [latest_status, latest_relevant_news] if item is not None],
            )

        if panic.position_risk_stage == PositionRiskStage.observe:
            fingerprint = self._notification_fingerprint(
                "position-observe",
                product_id,
                round(panic.position_drawdown_pct or 0.0, 2),
            )
            notify_user = self.ctx.state.should_emit_notification(
                f"autopilot:{product_id}:position-observe",
                fingerprint,
                workflow.panic_notify_cooldown_minutes,
            )
            return AutopilotDecision(
                phase=AutopilotPhase.observe,
                notify_user=notify_user,
                reason="position_drawdown_requires_attention",
                product_id=product_id,
                flow_mode=workflow.entry_mode,
                signal=signal,
                risk=risk,
                panic=panic,
                latest_news=[item for item in [latest_status, latest_relevant_news] if item is not None],
            )

        if panic.should_exit:
            fingerprint = self._notification_fingerprint(
                "panic",
                product_id,
                ",".join(panic.triggers),
                round(panic.daily_drawdown_pct or 0.0, 2),
                latest_status.title if latest_status else "",
            )
            notify_user = self.ctx.state.should_emit_notification(
                f"autopilot:{product_id}:panic",
                fingerprint,
                workflow.panic_notify_cooldown_minutes,
            )
            return AutopilotDecision(
                phase=AutopilotPhase.panic_exit,
                notify_user=notify_user,
                reason="risk_layer_approved_emergency_exit",
                product_id=product_id,
                flow_mode=workflow.entry_mode,
                signal=signal,
                risk=risk,
                panic=panic,
                latest_news=[item for item in [latest_status, latest_relevant_news] if item is not None],
            )

        if latest_status and latest_status.severity in {"medium", "high"}:
            fingerprint = self._notification_fingerprint(
                "exchange-status",
                product_id,
                latest_status.severity,
                latest_status.title,
            )
            notify_user = self.ctx.state.should_emit_notification(
                f"autopilot:{product_id}:exchange-status",
                fingerprint,
                workflow.news_notify_cooldown_minutes,
            )
            return AutopilotDecision(
                phase=AutopilotPhase.observe,
                notify_user=notify_user,
                reason="exchange_status_requires_observation",
                product_id=product_id,
                flow_mode=workflow.entry_mode,
                signal=signal,
                risk=risk,
                panic=panic,
                latest_news=[latest_status],
            )

        if (
            workflow.auto_preview_on_signal
            and workflow.entry_mode.value in {"confirm", "auto"}
            and signal.side.value == "long"
            and risk.approved
            and signal.confidence >= workflow.preview_min_confidence
        ):
            if workflow.entry_mode.value == "auto" and self.ctx.runtime.app.allow_live_orders:
                trade_result = self.buy_live(signal.quote_size_usd or Decimal("0"), product_id)
                fingerprint = self._notification_fingerprint(
                    "trade",
                    product_id,
                    signal.side.value,
                    round(signal.confidence, 2),
                    signal.reason,
                    signal.quote_size_usd or "",
                    trade_result.order_id or "",
                )
                notify_user = self.ctx.state.should_emit_notification(
                    f"autopilot:{product_id}:trade",
                    fingerprint,
                    workflow.signal_notify_cooldown_minutes,
                )
                return AutopilotDecision(
                    phase=AutopilotPhase.trade,
                    notify_user=notify_user,
                    reason="live_buy_executed_automatically",
                    product_id=product_id,
                    flow_mode=workflow.entry_mode,
                    preview_generated=False,
                    signal=signal,
                    risk=risk,
                    panic=panic,
                    latest_news=[latest_relevant_news] if latest_relevant_news is not None else [],
                    preview={
                        "order": trade_result.model_dump(mode="json"),
                    },
                )

            preview_payload, _ = self.preview_buy(signal.quote_size_usd or Decimal("0"), product_id)
            preview_order = preview_payload.get("preview") or {}
            preview_raw = preview_order.get("raw") or {}
            commission_total = preview_raw.get("commission_total")
            if commission_total is None:
                commission_total = (preview_raw.get("commission_detail_total") or {}).get("total_commission")
            preview_summary = {
                "success": preview_order.get("success"),
                "product_id": preview_order.get("product_id"),
                "side": preview_order.get("side"),
                "quote_size_usd": str(signal.quote_size_usd or Decimal("0")),
                "base_size": preview_raw.get("base_size"),
                "quote_after_commission": preview_raw.get("quote_size"),
                "est_average_filled_price": preview_raw.get("est_average_filled_price"),
                "commission_total": commission_total,
                "preview_id": preview_order.get("preview_id"),
            }
            if preview_summary.get("success"):
                self.ctx.state.upsert_pending_entry(
                    product_id=product_id,
                    quote_size_usd=str(signal.quote_size_usd or Decimal("0")),
                    side="BUY",
                    reason=signal.reason,
                    stop_loss_pct=signal.stop_loss_pct,
                    take_profit_pct=signal.take_profit_pct,
                    confidence=signal.confidence,
                    source="autopilot_confirm",
                    preview_id=preview_summary.get("preview_id"),
                    payload={
                        "product_id": product_id,
                        "quote_size_usd": str(signal.quote_size_usd or Decimal("0")),
                        "reason": signal.reason,
                        "confidence": signal.confidence,
                        "stop_loss_pct": signal.stop_loss_pct,
                        "take_profit_pct": signal.take_profit_pct,
                        "preview": preview_summary,
                    },
                )
            fingerprint = self._notification_fingerprint(
                "confirm",
                product_id,
                signal.side.value,
                round(signal.confidence, 2),
                signal.reason,
                signal.quote_size_usd or "",
            )
            notify_user = self.ctx.state.should_emit_notification(
                f"autopilot:{product_id}:confirm",
                fingerprint,
                workflow.signal_notify_cooldown_minutes,
            )
            return AutopilotDecision(
                phase=AutopilotPhase.confirm,
                notify_user=notify_user,
                reason="preview_ready_waiting_for_user_confirmation",
                product_id=product_id,
                flow_mode=workflow.entry_mode,
                preview_generated=preview_payload.get("preview") is not None,
                signal=signal,
                risk=risk,
                panic=panic,
                latest_news=[latest_relevant_news] if latest_relevant_news is not None else [],
                preview={
                    "risk": preview_payload.get("risk"),
                    "preview": preview_summary,
                },
            )

        if latest_relevant_news is not None:
            fingerprint = self._notification_fingerprint(
                "news",
                product_id,
                latest_relevant_news.title,
                latest_relevant_news.published_at.isoformat() if latest_relevant_news.published_at else "",
            )
            notify_user = self.ctx.state.should_emit_notification(
                f"autopilot:{product_id}:news",
                fingerprint,
                workflow.news_notify_cooldown_minutes,
            )
            return AutopilotDecision(
                phase=AutopilotPhase.observe,
                notify_user=notify_user,
                reason="fresh_relevant_news_requires_observation",
                product_id=product_id,
                flow_mode=workflow.entry_mode,
                signal=signal,
                risk=risk,
                panic=panic,
                latest_news=[latest_relevant_news],
            )

        return AutopilotDecision(
            phase=AutopilotPhase.heartbeat,
            notify_user=False,
            reason="no_action",
            product_id=product_id,
            flow_mode=workflow.entry_mode,
            signal=signal,
            risk=risk,
            panic=panic,
        )

    def autopilot_message(self, product_id: str | None = None) -> dict[str, Any]:
        decision = self.autopilot_check(product_id)
        symbol = self._display_symbol(decision.product_id)

        if decision.phase == AutopilotPhase.heartbeat or not decision.notify_user:
            return {
                "should_send": False,
                "phase": decision.phase.value,
                "text": None,
                "decision": decision.model_dump(mode="json"),
            }

        if decision.phase == AutopilotPhase.observe:
            reason = (
                decision.latest_news[0].title
                if decision.latest_news
                else (decision.reason or "市场状态变化")
            )
            action = "暂不开新仓"
            if decision.reason == "position_drawdown_requires_risk_reduction":
                reason = f"仓位回撤达到 {self._format_pct(decision.panic.position_drawdown_pct, 1) if decision.panic else '-'}"
                action = "停止开新仓并收缩风险"
            elif decision.reason == "position_drawdown_requires_attention":
                reason = f"仓位回撤达到 {self._format_pct(decision.panic.position_drawdown_pct, 1) if decision.panic else '-'}"
                action = "暂不开新仓，关注仓位风险"
            return {
                "should_send": True,
                "phase": decision.phase.value,
                "text": "\n".join(
                    [
                        f"🔵👀 {symbol} 风险升高",
                        f"原因：{reason}",
                        f"动作：{action}",
                    ]
                ),
                "decision": decision.model_dump(mode="json"),
            }

        if decision.phase == AutopilotPhase.confirm and decision.signal is not None:
            return {
                "should_send": True,
                "phase": decision.phase.value,
                "text": "\n".join(
                    [
                        f"🔵💰 预览：{decision.product_id} 多",
                        f"理由：{decision.signal.reason}",
                        f"原始金额：{decision.signal.quote_size_usd or Decimal('0')} USDC",
                        "杠杆：1x",
                        f"止损/止盈：{self._format_pct((decision.signal.stop_loss_pct or 0) * 100, 1)} / {self._format_pct((decision.signal.take_profit_pct or 0) * 100, 1)}",
                        "回复：执行 / 取消",
                    ]
                ),
                "decision": decision.model_dump(mode="json"),
            }

        if decision.phase == AutopilotPhase.trade and decision.signal is not None:
            order = (decision.preview or {}).get("order") or {}
            success = bool(order.get("success"))
            title = f"🔵💰 已买入 {decision.product_id}" if success else f"🔵💰 自动买入失败 {decision.product_id}"
            result_line = f"原始金额：{decision.signal.quote_size_usd or Decimal('0')} USDC"
            leverage_line = "杠杆：1x"
            reason_line = f"原因：{decision.signal.reason}"
            return {
                "should_send": True,
                "phase": decision.phase.value,
                "text": "\n".join([title, result_line, leverage_line, reason_line]),
                "decision": decision.model_dump(mode="json"),
            }

        if decision.phase == AutopilotPhase.panic_exit and decision.panic is not None:
            result = self.panic_exit_live(decision.product_id)
            order = result.get("order") or {}
            success = bool(order.get("success"))
            title = f"🔵🚨 已清 {symbol}" if success else f"🔵🚨 {symbol} 紧急退出失败"
            outcome = "已执行保护性退出，后续由风控冷静规则自动决定是否重新入场" if success else (order.get("message") or "执行失败")
            return {
                "should_send": True,
                "phase": decision.phase.value,
                "text": "\n".join(
                    [
                        title,
                        f"触发：{self._panic_trigger_text(decision.panic)}",
                        f"结果：{outcome}",
                    ]
                ),
                "decision": decision.model_dump(mode="json"),
                "exit_result": result,
            }

        return {
            "should_send": False,
            "phase": decision.phase.value,
            "text": None,
            "decision": decision.model_dump(mode="json"),
        }

    def daily_report(self, product_id: str | None = None) -> dict[str, Any]:
        product_id = product_id or self.ctx.runtime.app.primary_product
        symbol = self._display_symbol(product_id)
        equity = self.total_equity_usd(product_id)
        position = self.current_position_quote_usd(product_id)
        baseline = self.daily_equity_baseline_usd(product_id)
        pnl_pct = float(((equity - baseline) / baseline) * Decimal("100")) if baseline > 0 else 0.0
        panic = self.evaluate_emergency_exit(product_id)
        signal, risk = self.evaluate_signal(product_id)

        if panic.should_exit or panic.position_risk_stage in {PositionRiskStage.observe, PositionRiskStage.reduce, PositionRiskStage.exit} or panic.latest_exchange_status_severity in {"medium", "high"}:
            conclusion = "风险升高"
        elif risk.approved and signal.side.value == "long":
            conclusion = "继续观察"
        else:
            conclusion = "当前波动范围安全"

        return {
            "product_id": product_id,
            "text": "\n".join(
                [
                    f"🔵🕘 权益 {equity:.2f} USDC | 持仓 {symbol} 原始金额 {position:.2f} USDC | 杠杆 1x | 当日PnL {self._format_pct(pnl_pct, 3, signed=True)}",
                    f"结论：{conclusion}",
                ]
            ),
            "equity_usd": str(equity),
            "position_quote_usd": str(position),
            "daily_pnl_pct": pnl_pct,
            "conclusion": conclusion,
            "signal": signal.model_dump(mode='json'),
            "risk": risk.model_dump(mode='json'),
            "panic": panic.model_dump(mode='json'),
        }

    def market_snapshot(self, product_id: str | None = None) -> MarketSnapshot:
        product_id = product_id or self.ctx.runtime.app.primary_product
        now = datetime.now(timezone.utc)
        end = int(now.timestamp())
        lookback_minutes = self.ctx.runtime.app.candle_lookback * 5
        start = int((now - timedelta(minutes=lookback_minutes)).timestamp())
        product = self.ctx.client.get_product(product_id)
        candles = self.ctx.client.get_candles(
            product_id,
            start=start,
            end=end,
            granularity=self.ctx.runtime.app.granularity,
            limit=self.ctx.runtime.app.candle_lookback,
        )
        return MarketSnapshot(product=product, candles=candles)

    def generate_signal(self, product_id: str | None = None):
        snapshot = self.market_snapshot(product_id)
        signal = generate_btc_trend_signal(snapshot)
        self.ctx.state.record_decision(signal)
        return signal

    def evaluate_signal(self, product_id: str | None = None):
        product_id = product_id or self.ctx.runtime.app.primary_product
        signal = self.generate_signal(product_id)
        position_risk = self.position_drawdown_state(product_id)
        risk = evaluate_signal(
            signal,
            self.ctx.runtime.risk,
            self.quote_balance(product_id),
            self.total_equity_usd(product_id),
            self.daily_equity_baseline_usd(product_id),
            self.current_position_quote_usd(product_id),
            position_drawdown_pct=position_risk["drawdown_pct"],
        )
        self.ctx.state.record_risk(signal.product_id, risk)
        return signal, risk

    def preview_buy(self, quote_size: Decimal, product_id: str | None = None) -> tuple[dict, object]:
        product_id = product_id or self.ctx.runtime.app.primary_product
        position_risk = self.position_drawdown_state(product_id)
        risk = evaluate_manual_buy(
            quote_size,
            product_id,
            self.ctx.runtime.risk,
            self.quote_balance(product_id),
            self.total_equity_usd(product_id),
            self.daily_equity_baseline_usd(product_id),
            self.current_position_quote_usd(product_id),
            position_drawdown_pct=position_risk["drawdown_pct"],
        )
        self.ctx.state.record_risk(product_id, risk)
        if not risk.approved:
            return {"risk": risk.model_dump(mode="json")}, risk
        preview = self.ctx.client.preview_market_order(product_id=product_id, side="BUY", quote_size=quote_size)
        self.ctx.state.record_order(preview)
        if preview.success:
            self.ctx.state.upsert_pending_entry(
                product_id=product_id,
                quote_size_usd=f"{quote_size:f}",
                side="BUY",
                reason="manual_or_autopilot_preview",
                stop_loss_pct=None,
                take_profit_pct=None,
                confidence=None,
                source="preview_buy",
                preview_id=preview.preview_id,
                payload={
                    "product_id": product_id,
                    "quote_size_usd": f"{quote_size:f}",
                    "preview_id": preview.preview_id,
                },
            )
        return {"risk": risk.model_dump(mode="json"), "preview": preview.model_dump(mode="json")}, risk

    def preview_exit_all(self, product_id: str | None = None) -> dict:
        product_id = product_id or self.ctx.runtime.app.primary_product
        exit_decision = self.evaluate_emergency_exit(product_id)
        base_balance = self.base_balance(product_id)
        base_size = (base_balance.available + base_balance.hold) if base_balance else Decimal("0")
        if base_size <= 0:
            return {"exit": exit_decision.model_dump(mode="json")}
        preview = self.ctx.client.preview_market_order(product_id=product_id, side="SELL", base_size=base_size)
        self.ctx.state.record_order(preview)
        return {"exit": exit_decision.model_dump(mode="json"), "preview": preview.model_dump(mode="json")}

    def buy_live(self, quote_size: Decimal, product_id: str | None = None) -> OrderResult:
        product_id = product_id or self.ctx.runtime.app.primary_product
        position_risk = self.position_drawdown_state(product_id)
        risk = evaluate_manual_buy(
            quote_size,
            product_id,
            self.ctx.runtime.risk,
            self.quote_balance(product_id),
            self.total_equity_usd(product_id),
            self.daily_equity_baseline_usd(product_id),
            self.current_position_quote_usd(product_id),
            position_drawdown_pct=position_risk["drawdown_pct"],
        )
        self.ctx.state.record_risk(product_id, risk)
        if not risk.approved:
            result = OrderResult(success=False, product_id=product_id, side="BUY", message=f"Risk blocked: {risk.reason}")
            self.ctx.state.record_order(result)
            return result
        preview = self.ctx.client.preview_market_order(product_id=product_id, side="BUY", quote_size=quote_size)
        self.ctx.state.record_order(preview)
        if not preview.success or not preview.preview_id:
            return preview
        result = self.ctx.client.create_market_order(
            product_id=product_id,
            side="BUY",
            quote_size=quote_size,
            preview_id=preview.preview_id,
        )
        self.ctx.state.record_order(result)
        if result.success:
            self.ctx.state.clear_pending_entry(product_id)
        return result

    def confirm_pending_entry(self, product_id: str | None = None) -> dict:
        product_id = product_id or self.ctx.runtime.app.primary_product
        pending = self.ctx.state.get_pending_entry(product_id)
        if not pending:
            return {
                "success": False,
                "product_id": product_id,
                "message": "No active pending entry",
            }
        quote_size = Decimal(str(pending["quote_size_usd"]))
        result = self.buy_live(quote_size, product_id)
        return {
            "success": result.success,
            "product_id": product_id,
            "quote_size_usd": f"{quote_size:f}",
            "order": result.model_dump(mode="json"),
        }

    def cancel_pending_entry(self, product_id: str | None = None) -> dict:
        product_id = product_id or self.ctx.runtime.app.primary_product
        pending = self.ctx.state.get_pending_entry(product_id)
        if not pending:
            return {
                "success": False,
                "product_id": product_id,
                "message": "No active pending entry",
            }
        self.ctx.state.clear_pending_entry(product_id)
        return {
            "success": True,
            "product_id": product_id,
            "quote_size_usd": pending["quote_size_usd"],
            "message": "Pending entry canceled",
        }

    def panic_exit_live(self, product_id: str | None = None) -> dict:
        product_id = product_id or self.ctx.runtime.app.primary_product
        exit_decision = self.evaluate_emergency_exit(product_id)
        if not exit_decision.should_exit:
            return {
                "exit": exit_decision.model_dump(mode="json"),
                "order": OrderResult(success=False, product_id=product_id, side="SELL", message=f"Emergency exit not approved: {exit_decision.reason}").model_dump(mode="json"),
            }

        base_balance = self.base_balance(product_id)
        base_size = (base_balance.available + base_balance.hold) if base_balance else Decimal("0")
        if base_size <= 0:
            return {
                "exit": exit_decision.model_dump(mode="json"),
                "order": OrderResult(success=False, product_id=product_id, side="SELL", message="No base asset position to exit").model_dump(mode="json"),
            }

        preview = self.ctx.client.preview_market_order(product_id=product_id, side="SELL", base_size=base_size)
        self.ctx.state.record_order(preview)
        if not preview.success or not preview.preview_id:
            return {"exit": exit_decision.model_dump(mode="json"), "order": preview.model_dump(mode="json")}

        result = self.ctx.client.create_market_order(
            product_id=product_id,
            side="SELL",
            base_size=base_size,
            preview_id=preview.preview_id,
        )
        self.ctx.state.record_order(result)
        return {"exit": exit_decision.model_dump(mode="json"), "order": result.model_dump(mode="json")}
