from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Any

from ...config import RuntimeConfig
from ...ml import PerpModelService
from ...models import (
    AutopilotDecision,
    AutopilotPhase,
    EmergencyExitDecision,
    EntryWorkflowMode,
    NewsItem,
    PositionRiskStage,
    RiskEvaluation,
    RiskProfile,
    SignalDecision,
    SignalSide,
)
from ...news.monitor import sync_news
from ...risk import classify_position_drawdown
from ...signals.simple_perp import generate_perp_trend_signal
from ...state import StateStore
from ...strategy import load_current_strategy
from ..base import PerpEngine
from .calculations import margin_to_notional, notional_to_margin, round_leverage_to_step
from .news import is_fresh_news, is_market_relevant_news, is_relevant_news
from .types import PerpSystemState


class PerpSupervisor:
    LEGACY_PANIC_ENTRY_LOCK_KEY = "perp:panic_entry_lock"
    PANIC_GLOBAL_BREAKER_KEY = "perp:panic_global_breaker"
    PANIC_EVENT_HISTORY_KEY = "perp:panic_event_history"
    PANIC_COIN_COOLDOWN_MINUTES = 30
    PANIC_GLOBAL_BREAKER_THRESHOLD = 2
    PANIC_GLOBAL_BREAKER_WINDOW = timedelta(hours=6)
    PANIC_GLOBAL_BREAKER_DURATION = timedelta(hours=4)
    NEUTRAL_SIGNAL_MEDIUM_OVERRIDE_SHARE_PCT = Decimal("10")
    NEUTRAL_SIGNAL_STRONG_OVERRIDE_SHARE_PCT = Decimal("20")
    NEUTRAL_SIGNAL_OVERRIDE_LEVERAGE = Decimal("1")

    def __init__(self, runtime: RuntimeConfig, state: StateStore, engine: PerpEngine) -> None:
        self.runtime = runtime
        self.state = state
        self.engine = engine
        self.model_service = PerpModelService(runtime=runtime, engine=engine)

    def coins(self) -> list[str]:
        coins = [coin.upper() for coin in (self.runtime.perps.coins or [self.runtime.perps.coin])]
        return list(dict.fromkeys(coins))

    def recent_news(self, max_age_minutes: int = 24 * 60, limit: int = 50) -> list[NewsItem]:
        sync_news(self.runtime.news, self.state)
        return self.state.list_recent_news(max_age_minutes=max_age_minutes, limit=limit)

    def portfolio(self):
        return self.engine.portfolio()

    def _notification_fingerprint(self, *parts: object) -> str:
        return sha256("|".join("" if part is None else str(part) for part in parts).encode("utf-8")).hexdigest()

    def _position_risk_key(self, coin: str) -> str:
        return f"perp-position-risk:{self.runtime.perps.exchange}:{coin.upper()}"

    def _panic_coin_cooldown_key(self, coin: str) -> str:
        return f"perp:panic_cooldown:{self.runtime.perps.exchange}:{coin.upper()}"

    def _position_identity(self, position) -> dict[str, str] | None:
        if position is None:
            return None
        return {
            "side": str(position.side),
            "entry_price": str(position.entry_price),
            "quantity": str(position.quantity),
        }

    def _write_position_risk_state(
        self,
        coin: str,
        *,
        peak_value_usd: Decimal,
        drawdown_pct: float,
        stage: PositionRiskStage,
        position_identity: dict[str, str] | None,
    ) -> dict[str, Any]:
        payload = {
            "coin": coin.upper(),
            "peak_value_usd": str(peak_value_usd),
            "drawdown_pct": drawdown_pct,
            "stage": stage.value,
            "position_identity": position_identity,
        }
        self.state.set_value(self._position_risk_key(coin), json.dumps(payload))
        return {
            "coin": coin.upper(),
            "peak_value_usd": peak_value_usd,
            "drawdown_pct": drawdown_pct,
            "stage": stage,
            "position_identity": position_identity,
        }

    def reset_position_drawdown_state(self, coin: str) -> dict[str, Any]:
        account = self.engine.account(coin)
        position = account.position
        current_value = self._position_value_usd(coin)
        if position is None or current_value <= 0:
            return self._write_position_risk_state(
                coin,
                peak_value_usd=Decimal("0"),
                drawdown_pct=0.0,
                stage=PositionRiskStage.normal,
                position_identity=None,
            )
        return self._write_position_risk_state(
            coin,
            peak_value_usd=current_value,
            drawdown_pct=0.0,
            stage=PositionRiskStage.normal,
            position_identity=self._position_identity(position),
        )

    def _parse_iso_timestamp(self, value: Any) -> datetime | None:
        if value in (None, ""):
            return None
        raw = str(value)
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    def _load_panic_event_history(self, *, now: datetime) -> list[dict[str, Any]]:
        raw = self.state.get_value(self.PANIC_EVENT_HISTORY_KEY)
        if not raw:
            return []
        try:
            payload = json.loads(raw)
        except Exception:
            return []
        if not isinstance(payload, list):
            return []
        cutoff = now - self.PANIC_GLOBAL_BREAKER_WINDOW
        items: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            occurred_at = self._parse_iso_timestamp(item.get("occurred_at"))
            if occurred_at is None or occurred_at < cutoff:
                continue
            items.append(dict(item))
        return items

    def _save_panic_event_history(self, items: list[dict[str, Any]], *, now: datetime) -> None:
        if items:
            self.state.set_value(self.PANIC_EVENT_HISTORY_KEY, json.dumps(items), now=now)
        else:
            self.state.delete_value(self.PANIC_EVENT_HISTORY_KEY)

    def panic_protection_status(self, *, now: datetime | None = None) -> dict[str, Any]:
        timestamp = (now or datetime.now(UTC)).astimezone(UTC)
        # Clear legacy manual-lock state so old deployments do not keep blocking entries.
        self.state.delete_value(self.LEGACY_PANIC_ENTRY_LOCK_KEY)

        global_breaker: dict[str, Any] | None = None
        raw_breaker = self.state.get_value(self.PANIC_GLOBAL_BREAKER_KEY)
        if raw_breaker:
            try:
                payload = json.loads(raw_breaker)
            except Exception:
                payload = {}
            if isinstance(payload, dict):
                until = self._parse_iso_timestamp(payload.get("until"))
                if until is not None and until > timestamp:
                    global_breaker = dict(payload)
                    global_breaker["active"] = True
                    global_breaker["until"] = until.isoformat()
                else:
                    self.state.delete_value(self.PANIC_GLOBAL_BREAKER_KEY)

        cooldowns: list[dict[str, Any]] = []
        for coin in self.coins():
            raw = self.state.get_value(self._panic_coin_cooldown_key(coin))
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            until = self._parse_iso_timestamp(payload.get("until"))
            if until is None or until <= timestamp:
                self.state.delete_value(self._panic_coin_cooldown_key(coin))
                continue
            payload = dict(payload)
            payload["coin"] = coin.upper()
            payload["active"] = True
            payload["until"] = until.isoformat()
            cooldowns.append(payload)

        recent_events = self._load_panic_event_history(now=timestamp)
        self._save_panic_event_history(recent_events, now=timestamp)
        return {
            "active": bool(global_breaker or cooldowns),
            "global_breaker_active": global_breaker is not None,
            "global_breaker": global_breaker,
            "coin_cooldowns": cooldowns,
            "recent_panic_events": recent_events,
            "cooldown_minutes": self.PANIC_COIN_COOLDOWN_MINUTES,
            "breaker_threshold": self.PANIC_GLOBAL_BREAKER_THRESHOLD,
            "breaker_window_hours": int(self.PANIC_GLOBAL_BREAKER_WINDOW.total_seconds() // 3600),
            "breaker_duration_hours": int(self.PANIC_GLOBAL_BREAKER_DURATION.total_seconds() // 3600),
        }

    def panic_entry_lock_status(self) -> dict[str, Any]:
        return self.panic_protection_status()

    def register_panic_exit(
        self,
        *,
        now: datetime | None = None,
        coin: str,
        trigger_reason: str,
        trigger_product_id: str | None = None,
        trigger_triggers: list[str] | None = None,
    ) -> dict[str, Any]:
        timestamp = (now or datetime.now(UTC)).astimezone(UTC)
        coin_upper = coin.upper()
        cooldown_until = timestamp + timedelta(minutes=self.PANIC_COIN_COOLDOWN_MINUTES)
        cooldown_payload = {
            "coin": coin_upper,
            "trigger_reason": trigger_reason,
            "trigger_product_id": trigger_product_id,
            "trigger_triggers": trigger_triggers or [],
            "triggered_at": timestamp.isoformat(),
            "until": cooldown_until.isoformat(),
        }
        self.state.set_value(
            self._panic_coin_cooldown_key(coin_upper),
            json.dumps(cooldown_payload),
            now=timestamp,
        )

        events = self._load_panic_event_history(now=timestamp)
        events.append(
            {
                "coin": coin_upper,
                "trigger_reason": trigger_reason,
                "trigger_product_id": trigger_product_id,
                "trigger_triggers": trigger_triggers or [],
                "occurred_at": timestamp.isoformat(),
            }
        )
        self._save_panic_event_history(events, now=timestamp)

        if len(events) >= self.PANIC_GLOBAL_BREAKER_THRESHOLD:
            existing = self.panic_protection_status(now=timestamp).get("global_breaker") or {}
            existing_until = self._parse_iso_timestamp(existing.get("until"))
            breaker_until = timestamp + self.PANIC_GLOBAL_BREAKER_DURATION
            if existing_until is not None and existing_until > breaker_until:
                breaker_until = existing_until
            breaker_payload = {
                "trigger_reason": trigger_reason,
                "trigger_product_id": trigger_product_id,
                "trigger_triggers": trigger_triggers or [],
                "triggered_at": timestamp.isoformat(),
                "until": breaker_until.isoformat(),
                "recent_panic_count": len(events),
            }
            self.state.set_value(self.PANIC_GLOBAL_BREAKER_KEY, json.dumps(breaker_payload), now=timestamp)
        return self.panic_protection_status(now=timestamp)

    def set_panic_entry_lock(
        self,
        *,
        now: datetime | None = None,
        trigger_reason: str,
        trigger_product_id: str | None = None,
        trigger_triggers: list[str] | None = None,
    ) -> dict[str, Any]:
        default_coin = (trigger_product_id or self.runtime.perps.coin or "BTC").split("-")[0]
        return self.register_panic_exit(
            now=now,
            coin=default_coin,
            trigger_reason=trigger_reason,
            trigger_product_id=trigger_product_id,
            trigger_triggers=trigger_triggers,
        )

    def clear_panic_protection(self, *, now: datetime | None = None, cleared_by: str = "manual_override") -> dict[str, Any]:
        previous = self.panic_protection_status(now=now)
        self.state.delete_value(self.LEGACY_PANIC_ENTRY_LOCK_KEY)
        self.state.delete_value(self.PANIC_GLOBAL_BREAKER_KEY)
        self.state.delete_value(self.PANIC_EVENT_HISTORY_KEY)
        for coin in self.coins():
            self.state.delete_value(self._panic_coin_cooldown_key(coin))
        return {
            "active": False,
            "cleared_at": (now or datetime.now(UTC)).astimezone(UTC).isoformat(),
            "cleared_by": cleared_by,
            "previous": previous if previous.get("active") else None,
        }

    def clear_panic_entry_lock(self, *, now: datetime | None = None, cleared_by: str = "manual_override") -> dict[str, Any]:
        return self.clear_panic_protection(now=now, cleared_by=cleared_by)

    def _strategy_symbol(self, coin: str) -> dict[str, Any]:
        strategy = load_current_strategy() or {}
        for item in strategy.get("symbols", []):
            symbol = str(item.get("symbol", "")).upper()
            if symbol in {coin.upper(), f"{coin.upper()}-PERP"}:
                return item
        return {}

    def _exposure_budget_usd(self, total_equity_usd: Decimal) -> Decimal:
        hard_total_exposure_pct = min(
            max(self.runtime.perps.max_total_exposure_pct_of_equity, 0.0),
            100.0,
        )
        return total_equity_usd * Decimal(str(hard_total_exposure_pct / 100))

    def _notional_budget_usd(self, total_equity_usd: Decimal, *, leverage: Decimal | None = None) -> Decimal:
        effective_leverage = leverage if leverage is not None else self._effective_max_leverage()
        return self._exposure_budget_usd(total_equity_usd) * max(effective_leverage, Decimal("0"))

    @staticmethod
    def _margin_to_notional(margin_usd: Decimal, leverage: Decimal) -> Decimal:
        return margin_to_notional(margin_usd, leverage)

    @staticmethod
    def _notional_to_margin(notional_usd: Decimal, leverage: Decimal) -> Decimal:
        return notional_to_margin(notional_usd, leverage)

    def _effective_leverage_bounds(self) -> tuple[Decimal, Decimal]:
        strategy = load_current_strategy() or {}
        hard_min_leverage = 1.0
        hard_max_leverage = max(float(self.runtime.perps.max_leverage), hard_min_leverage)
        try:
            soft_max_leverage = float(strategy.get("soft_max_leverage", hard_max_leverage))
        except Exception:
            soft_max_leverage = hard_max_leverage
        try:
            soft_min_leverage = float(strategy.get("soft_min_leverage", hard_min_leverage))
        except Exception:
            soft_min_leverage = hard_min_leverage
        soft_max_leverage = min(max(soft_max_leverage, hard_min_leverage), hard_max_leverage)
        soft_min_leverage = min(max(soft_min_leverage, hard_min_leverage), hard_max_leverage)
        if soft_max_leverage < soft_min_leverage:
            soft_max_leverage = soft_min_leverage
        return (Decimal(str(soft_min_leverage)), Decimal(str(soft_max_leverage)))

    def _effective_min_leverage(self) -> Decimal:
        min_leverage, _ = self._effective_leverage_bounds()
        return min_leverage

    def _effective_max_leverage(self) -> Decimal:
        _, max_leverage = self._effective_leverage_bounds()
        return max_leverage

    @staticmethod
    def _round_leverage_to_step(value: Decimal, *, step: Decimal = Decimal("0.5")) -> Decimal:
        return round_leverage_to_step(value, step=step)

    def _tiered_signal_leverage(self, signal: SignalDecision) -> Decimal:
        min_leverage = self._effective_min_leverage()
        max_leverage = self._effective_max_leverage()
        if signal.side == SignalSide.flat or max_leverage <= min_leverage:
            return min_leverage
        confidence = max(0.0, min(float(signal.confidence or 0.0), 1.0))
        weak_threshold = float(self.runtime.strategy.weak_signal_confidence)
        strong_threshold = float(self.runtime.strategy.strong_signal_confidence)
        span = max_leverage - min_leverage
        if confidence >= strong_threshold:
            target = max_leverage
        elif confidence >= weak_threshold:
            target = min_leverage + (span * Decimal("0.5"))
        else:
            target = min_leverage + (span * Decimal("0.25"))
        target = self._round_leverage_to_step(target)
        return min(max(target, min_leverage), max_leverage)

    def _symbol_limits(
        self,
        coin: str,
        total_equity_usd: Decimal,
        *,
        leverage: Decimal | None = None,
        neutral_override: dict[str, Any] | None = None,
    ) -> tuple[Decimal, Decimal, str]:
        strategy_item = self._strategy_symbol(coin)
        target_position_share_pct = float(
            strategy_item.get(
                "target_position_share_pct",
                strategy_item.get(
                    "max_position_share_pct",
                    strategy_item.get("max_position_pct", self.runtime.perps.max_position_share_pct_of_exposure_budget),
                ),
            )
        )
        max_order_share_pct = float(self.runtime.perps.max_order_share_pct_of_exposure_budget)
        bias = str(strategy_item.get("bias", "neutral")).lower()
        if neutral_override is not None:
            target_position_share_pct = float(neutral_override["target_position_share_pct"])
            max_order_share_pct = float(neutral_override["max_order_share_pct"])
        notional_budget = self._notional_budget_usd(total_equity_usd, leverage=leverage)
        max_position = notional_budget * Decimal(str(target_position_share_pct / 100))
        max_order = notional_budget * Decimal(str(max_order_share_pct / 100))
        return max_position, max_order, bias

    def _neutral_signal_override(
        self,
        coin: str,
        signal: SignalDecision,
        *,
        allow_existing_position: bool,
    ) -> dict[str, Any] | None:
        if not self.runtime.strategy.enable_neutral_signal_override:
            return None
        if allow_existing_position:
            return None
        if signal.side not in {SignalSide.long, SignalSide.short}:
            return None
        confidence = float(signal.confidence or 0.0)
        strong_threshold = float(self.runtime.strategy.strong_signal_confidence)
        weak_threshold = float(self.runtime.strategy.weak_signal_confidence)
        if confidence < weak_threshold:
            return None
        strategy_item = self._strategy_symbol(coin)
        bias = str(strategy_item.get("bias", "neutral")).lower()
        target_position_share_pct = float(
            strategy_item.get(
                "target_position_share_pct",
                strategy_item.get(
                    "max_position_share_pct",
                    strategy_item.get("max_position_pct", self.runtime.perps.max_position_share_pct_of_exposure_budget),
                ),
            )
        )
        if bias != "neutral" or target_position_share_pct > 0:
            return None
        override_share_pct = (
            self.NEUTRAL_SIGNAL_STRONG_OVERRIDE_SHARE_PCT
            if confidence >= strong_threshold
            else self.NEUTRAL_SIGNAL_MEDIUM_OVERRIDE_SHARE_PCT
        )
        return {
            "target_position_share_pct": override_share_pct,
            "max_order_share_pct": override_share_pct,
            "execution_leverage": self.NEUTRAL_SIGNAL_OVERRIDE_LEVERAGE,
            "desired_side": signal.side.value,
            "tier": "strong" if confidence >= strong_threshold else "medium",
        }

    def _minimum_trade_notional_usd(self, coin: str) -> Decimal:
        try:
            return max(self.engine.minimum_trade_notional_usd(coin), Decimal("0"))
        except Exception:
            return Decimal("0")

    def _strategy_target(
        self,
        coin: str,
        *,
        signal: SignalDecision,
        total_equity_usd: Decimal,
        total_exposure_usd: Decimal,
        current_position_quote_usd: Decimal,
        total_margin_used_usd: Decimal | None = None,
        current_position_margin_usd: Decimal | None = None,
    ) -> dict[str, Any]:
        neutral_override = self._neutral_signal_override(
            coin,
            signal,
            allow_existing_position=current_position_quote_usd > 0,
        )
        min_leverage = self._effective_min_leverage()
        max_leverage = self._effective_max_leverage()
        try:
            raw_leverage = Decimal(str(signal.leverage))
        except Exception:
            raw_leverage = max_leverage
        if neutral_override is not None:
            raw_leverage = Decimal(str(neutral_override["execution_leverage"]))
        leverage = min(max(raw_leverage, min_leverage), max_leverage)
        max_position, max_order, bias = self._symbol_limits(
            coin,
            total_equity_usd,
            leverage=leverage,
            neutral_override=neutral_override,
        )
        max_position_margin = self._notional_to_margin(max_position, leverage)
        max_order_margin = self._notional_to_margin(max_order, leverage)
        desired_side: str | None = None
        if neutral_override is not None:
            desired_side = str(neutral_override["desired_side"])
        elif bias == "long":
            desired_side = "long"
        elif bias == "short":
            desired_side = "short"
        exposure_budget = self._exposure_budget_usd(total_equity_usd)
        current_margin = (
            max(current_position_margin_usd, Decimal("0"))
            if current_position_margin_usd is not None
            else self._notional_to_margin(current_position_quote_usd, leverage)
        )
        total_margin = (
            max(total_margin_used_usd, Decimal("0"))
            if total_margin_used_usd is not None
            else self._notional_to_margin(total_exposure_usd, leverage)
        )
        other_margin = max(total_margin - current_margin, Decimal("0"))
        available_margin_capacity = max(exposure_budget - other_margin, Decimal("0"))
        target_margin = min(max_position_margin if desired_side is not None else Decimal("0"), available_margin_capacity)
        target_notional = self._margin_to_notional(target_margin, leverage)
        notional_budget = self._notional_budget_usd(total_equity_usd, leverage=leverage)
        return {
            "bias": bias,
            "desired_side": desired_side,
            "target_notional_usd": max(target_notional, Decimal("0")),
            "target_margin_usd": max(target_margin, Decimal("0")),
            "max_position_usd": max(max_position, Decimal("0")),
            "max_position_margin_usd": max(max_position_margin, Decimal("0")),
            "max_order_usd": max(max_order, Decimal("0")),
            "max_order_margin_usd": max(max_order_margin, Decimal("0")),
            "current_margin_usd": current_margin,
            "minimum_notional_usd": self._minimum_trade_notional_usd(coin),
            "available_position_capacity_usd": self._margin_to_notional(available_margin_capacity, leverage),
            "available_position_capacity_margin_usd": available_margin_capacity,
            "notional_budget_usd": notional_budget,
            "exposure_budget_usd": exposure_budget,
            "effective_min_leverage": min_leverage,
            "effective_max_leverage": leverage,
            "neutral_override_active": neutral_override is not None,
        }

    def model_status(self, coin: str) -> dict[str, Any]:
        return self.model_service.model_status(coin)

    def _position_value_usd(self, coin: str) -> Decimal:
        account = self.engine.account(coin)
        if account.position is None:
            return Decimal("0")
        return max(account.position.margin_used_usd + account.unrealized_pnl_usd, Decimal("0"))

    def position_drawdown_state(self, coin: str) -> dict[str, Any]:
        account = self.engine.account(coin)
        position = account.position
        current_value = self._position_value_usd(coin)
        if position is None or current_value <= 0:
            return self._write_position_risk_state(
                coin,
                peak_value_usd=Decimal("0"),
                drawdown_pct=0.0,
                stage=PositionRiskStage.normal,
                position_identity=None,
            )
        raw = self.state.get_value(self._position_risk_key(coin))
        peak_value = current_value
        current_identity = self._position_identity(position)
        if raw:
            try:
                payload = json.loads(raw)
                stored_identity = payload.get("position_identity")
                if stored_identity == current_identity:
                    peak_value = Decimal(str(payload.get("peak_value_usd", str(current_value))))
            except Exception:
                peak_value = current_value
        peak_value = max(peak_value, current_value)
        drawdown_pct = float(((peak_value - current_value) / peak_value) * Decimal("100")) if peak_value > 0 else 0.0
        stage = classify_position_drawdown(drawdown_pct, self.runtime.risk)
        return self._write_position_risk_state(
            coin,
            peak_value_usd=peak_value,
            drawdown_pct=drawdown_pct,
            stage=stage,
            position_identity=current_identity,
        )

    def _is_fresh_news(self, item: NewsItem, max_age_minutes: int) -> bool:
        return is_fresh_news(item, max_age_minutes)

    def _is_relevant_news(self, item: NewsItem, coin: str) -> bool:
        return is_relevant_news(item, coin, exchange=self.runtime.perps.exchange)

    def _is_market_relevant_news(self, item: NewsItem) -> bool:
        return is_market_relevant_news(item, exchange=self.runtime.perps.exchange)

    def strategy_news(self, max_age_minutes: int = 24 * 60, limit: int = 20) -> list[NewsItem]:
        return [item for item in self.recent_news(max_age_minutes=max_age_minutes, limit=limit) if self._is_market_relevant_news(item)]

    def evaluate_emergency_exit(self, coin: str) -> EmergencyExitDecision:
        position = self.engine.position(coin)
        position_risk = self.position_drawdown_state(coin)
        latest_exchange_status_title = None
        latest_exchange_status_severity = None
        triggers: list[str] = []
        if position is None:
            return EmergencyExitDecision(
                should_exit=False,
                reason="no_open_position",
                triggers=[],
                position_drawdown_pct=position_risk["drawdown_pct"],
                position_risk_stage=position_risk["stage"],
            )
        news_items = self.recent_news(limit=20)
        for item in news_items:
            if item.layer == "exchange-status" and self._is_market_relevant_news(item):
                latest_exchange_status_title = item.title
                latest_exchange_status_severity = item.severity
                if self.runtime.risk.emergency_exit_enabled and self.runtime.risk.emergency_exit_on_exchange_status and item.severity == "high":
                    triggers.append("exchange_status_high_severity")
                break
        if self.runtime.risk.emergency_exit_enabled and position_risk["stage"] == PositionRiskStage.exit:
            triggers.append("position_drawdown_exit")
        return EmergencyExitDecision(
            should_exit=bool(triggers),
            reason="approved_emergency_exit" if triggers else "no_hard_exit_trigger",
            triggers=triggers,
            current_position_quote_usd=position.notional_usd,
            position_peak_quote_usd=position_risk["peak_value_usd"],
            position_drawdown_pct=position_risk["drawdown_pct"],
            position_risk_stage=position_risk["stage"],
            latest_exchange_status_title=latest_exchange_status_title,
            latest_exchange_status_severity=latest_exchange_status_severity,
        )

    def evaluate_signal(self, coin: str) -> tuple[SignalDecision, RiskEvaluation]:
        portfolio = self.portfolio()
        effective_min_leverage = self._effective_min_leverage()
        effective_max_leverage = self._effective_max_leverage()
        prediction_leverage = effective_max_leverage
        _prediction_max_position, prediction_max_order, bias = self._symbol_limits(
            coin,
            portfolio.total_equity_usd,
            leverage=prediction_leverage,
        )
        prediction_notional_budget = self._notional_budget_usd(
            portfolio.total_equity_usd,
            leverage=prediction_leverage,
        )
        try:
            model_prediction = self.model_service.predict(
                coin,
                max_order_quote_usd=prediction_max_order,
                leverage=prediction_leverage,
            )
            signal = model_prediction.signal
            signal.metadata["signal_source"] = "model"
            signal.metadata["model_available"] = True
            signal.metadata.setdefault("regime", model_prediction.regime["label"])
            signal.metadata.setdefault("regime_confidence", model_prediction.regime["confidence"])
        except Exception as exc:
            signal = generate_perp_trend_signal(
                symbol=f"{coin.upper()}-PERP",
                candles=self.engine.candles(coin, interval="15m", lookback=48),
                max_order_quote_usd=prediction_max_order,
                leverage=prediction_leverage,
            )
            signal.metadata["signal_source"] = "heuristic_fallback"
            signal.metadata["model_available"] = False
            signal.metadata["model_error"] = str(exc)
            signal.metadata["model_fallback"] = str(exc)
        if bias == "avoid":
            signal.side = SignalSide.flat
            signal.reason = "Daily strategy marks this coin as avoid."
            signal.quote_size_usd = Decimal("0")
            signal.risk_profile = RiskProfile.defensive
        elif bias == "long" and signal.side == SignalSide.short:
            signal.side = SignalSide.flat
            signal.reason = "Daily strategy allows only long exposure here."
            signal.quote_size_usd = Decimal("0")
        elif bias == "short" and signal.side == SignalSide.long:
            signal.side = SignalSide.flat
            signal.reason = "Daily strategy allows only short exposure here."
            signal.quote_size_usd = Decimal("0")
        original_quote = signal.quote_size_usd or Decimal("0")
        size_ratio = Decimal("0")
        if prediction_max_order > 0 and original_quote > 0:
            size_ratio = min(max(original_quote / prediction_max_order, Decimal("0")), Decimal("1"))
        position = self.engine.position(coin)
        neutral_override = self._neutral_signal_override(
            coin,
            signal,
            allow_existing_position=position is not None,
        )
        signal.leverage = (
            Decimal(str(neutral_override["execution_leverage"]))
            if neutral_override is not None
            else self._tiered_signal_leverage(signal)
        )
        signal.metadata["leverage_policy"] = "confidence_tiered"
        signal.metadata["prediction_leverage"] = str(prediction_leverage)
        signal.metadata["suggested_execution_leverage"] = str(signal.leverage)
        signal.metadata["neutral_signal_override_active"] = neutral_override is not None
        if neutral_override is not None:
            signal.metadata["neutral_signal_override_tier"] = str(neutral_override.get("tier"))
        max_position, max_order, _ = self._symbol_limits(
            coin,
            portfolio.total_equity_usd,
            leverage=signal.leverage,
            neutral_override=neutral_override,
        )
        notional_budget = self._notional_budget_usd(
            portfolio.total_equity_usd,
            leverage=signal.leverage,
        )
        if signal.side == SignalSide.flat or size_ratio <= 0:
            signal.quote_size_usd = Decimal("0")
        elif neutral_override is not None:
            signal.quote_size_usd = min(original_quote, max_order).quantize(Decimal("0.00000001"))
        else:
            signal.quote_size_usd = (max_order * size_ratio).quantize(Decimal("0.00000001"))

        current_position_quote = position.notional_usd if position is not None else Decimal("0")
        remaining_capacity = max(max_position - current_position_quote, Decimal("0"))
        proposed_quote = signal.quote_size_usd or Decimal("0")
        is_flip_candidate = position is not None and signal.side in {SignalSide.long, SignalSide.short} and signal.side.value != position.side
        max_trade_quote = min(max_order, max_position if is_flip_candidate else remaining_capacity)
        projected_exposure = portfolio.total_exposure_usd
        if signal.side != SignalSide.flat:
            if position is None:
                projected_exposure += proposed_quote
            elif is_flip_candidate:
                projected_exposure = max(portfolio.total_exposure_usd - current_position_quote, Decimal("0")) + proposed_quote
        blocked: list[str] = []
        position_risk = self.position_drawdown_state(coin)
        stage = position_risk["stage"]
        position_drawdown_pct = position_risk["drawdown_pct"]
        if signal.side != SignalSide.flat and proposed_quote > max_trade_quote:
            blocked.append("signal_quote_above_limit")
        if signal.side != SignalSide.flat and projected_exposure > notional_budget:
            blocked.append("total_exposure_above_limit")
        if Decimal(str(signal.leverage)) > effective_max_leverage:
            blocked.append("leverage_above_limit")
        if stage in {PositionRiskStage.reduce, PositionRiskStage.exit}:
            blocked.append("position_drawdown_risk_high")
        approved = not blocked and signal.side != SignalSide.flat and max_trade_quote > 0
        risk = RiskEvaluation(
            approved=approved,
            reason="approved" if approved else ",".join(blocked) or "flat_signal",
            max_allowed_quote_usd=max_trade_quote,
            total_equity_usd=portfolio.total_equity_usd,
            daily_equity_baseline_usd=portfolio.starting_equity_usd,
            daily_drawdown_pct=None,
            current_position_quote_usd=current_position_quote,
            remaining_capacity_quote_usd=remaining_capacity,
            max_order_pct_of_equity=float(max_order / portfolio.total_equity_usd * Decimal("100")) if portfolio.total_equity_usd > 0 else 0.0,
            max_position_pct_of_equity=float(max_position / portfolio.total_equity_usd * Decimal("100")) if portfolio.total_equity_usd > 0 else 0.0,
            max_order_share_pct_of_exposure_budget=(
                float(max_order / notional_budget * Decimal("100"))
                if notional_budget > 0
                else 0.0
            ),
            max_position_share_pct_of_exposure_budget=(
                float(max_position / notional_budget * Decimal("100"))
                if notional_budget > 0
                else 0.0
            ),
            position_drawdown_pct=position_drawdown_pct,
            position_risk_stage=stage,
            blocked_rules=blocked,
        )
        signal.metadata.update(
            {
                "prediction_notional_budget_usd": str(prediction_notional_budget),
                "strategy_bias": bias,
                "current_position_quote_usd": str(current_position_quote),
                "remaining_capacity_quote_usd": str(remaining_capacity),
                "projected_exposure_quote_usd": str(projected_exposure),
            }
        )
        return signal, risk

    def autopilot_check(self, coin: str) -> AutopilotDecision:
        workflow = self.runtime.workflow
        signal, risk = self.evaluate_signal(coin)
        panic = self.evaluate_emergency_exit(coin)
        position = self.engine.position(coin)
        news_items = self.recent_news(limit=20)
        latest_relevant_news = next(
            (
                item for item in news_items
                if item.layer != "exchange-status"
                and self._is_market_relevant_news(item)
                and self._is_fresh_news(item, workflow.fresh_news_minutes)
                and self._is_relevant_news(item, coin)
            ),
            None,
        )
        latest_status = next((item for item in news_items if item.layer == "exchange-status" and self._is_market_relevant_news(item)), None)
        symbol = f"{coin.upper()}-PERP"
        portfolio = self.portfolio()
        current_position_quote = position.notional_usd if position is not None else Decimal("0")
        current_position_margin = position.margin_used_usd if position is not None else Decimal("0")
        total_margin_used = sum((item.margin_used_usd for item in portfolio.positions), Decimal("0"))
        strategy_target = self._strategy_target(
            coin,
            signal=signal,
            total_equity_usd=portfolio.total_equity_usd,
            total_exposure_usd=portfolio.total_exposure_usd,
            current_position_quote_usd=current_position_quote,
            total_margin_used_usd=total_margin_used,
            current_position_margin_usd=current_position_margin,
        )
        minimum_notional = strategy_target["minimum_notional_usd"]
        min_actionable_notional = max(minimum_notional, Decimal("0.01"))
        signal.metadata.update(
            {
                "strategy_bias": strategy_target["bias"],
                "strategy_target_side": strategy_target["desired_side"],
                "strategy_target_quote_usd": str(strategy_target["target_notional_usd"]),
                "strategy_target_margin_usd": str(strategy_target["target_margin_usd"]),
                "strategy_max_order_quote_usd": str(strategy_target["max_order_usd"]),
                "strategy_max_order_margin_usd": str(strategy_target["max_order_margin_usd"]),
                "strategy_effective_min_leverage": str(strategy_target["effective_min_leverage"]),
                "strategy_effective_max_leverage": str(strategy_target["effective_max_leverage"]),
                "strategy_exposure_budget_usd": str(strategy_target["exposure_budget_usd"]),
                "strategy_current_margin_usd": str(strategy_target["current_margin_usd"]),
                "minimum_trade_notional_usd": str(minimum_notional),
            }
        )
        panic_protection = self.panic_protection_status()
        global_breaker = panic_protection.get("global_breaker") or {}
        coin_cooldown = next(
            (
                item
                for item in panic_protection.get("coin_cooldowns", [])
                if str(item.get("coin", "")).upper() == coin.upper()
            ),
            None,
        )
        global_breaker_active = bool(panic_protection.get("global_breaker_active"))
        coin_cooldown_active = coin_cooldown is not None
        panic_reentry_block_active = global_breaker_active or coin_cooldown_active
        signal.metadata["panic_entry_lock_active"] = panic_reentry_block_active
        signal.metadata["panic_protection_active"] = panic_reentry_block_active
        signal.metadata["panic_global_breaker_active"] = global_breaker_active
        signal.metadata["panic_coin_cooldown_active"] = coin_cooldown_active
        if global_breaker_active:
            signal.metadata["panic_global_breaker_until"] = global_breaker.get("until")
        if coin_cooldown_active:
            signal.metadata["panic_coin_cooldown_until"] = coin_cooldown.get("until")
        if panic_reentry_block_active:
            signal.metadata["panic_entry_lock_reason"] = (
                "panic_global_breaker_active" if global_breaker_active else "panic_coin_cooldown_active"
            )

        if panic.position_risk_stage == PositionRiskStage.reduce:
            fp = self._notification_fingerprint("perp-reduce", symbol, round(panic.position_drawdown_pct or 0.0, 2))
            notify = self.state.should_emit_notification(f"perp:{symbol}:reduce", fp, workflow.panic_notify_cooldown_minutes)
            if position is not None:
                signal.metadata["strategy_plan_status"] = "ready"
                signal.metadata["strategy_plan_reason"] = "position_drawdown_requires_risk_reduction"
                return AutopilotDecision(
                    phase=AutopilotPhase.trade,
                    notify_user=notify,
                    reason="position_drawdown_requires_risk_reduction",
                    product_id=symbol,
                    flow_mode=workflow.entry_mode,
                    signal=signal,
                    risk=risk,
                    panic=panic,
                    latest_news=[item for item in [latest_status, latest_relevant_news] if item],
                    preview={"plan": {"action": "close", "side": position.side, "notional_usd": str(position.notional_usd), "coin": coin.upper(), "minimum_trade_notional_usd": str(minimum_notional)}},
                )
            return AutopilotDecision(phase=AutopilotPhase.observe, notify_user=notify, reason="position_drawdown_requires_risk_reduction", product_id=symbol, flow_mode=workflow.entry_mode, signal=signal, risk=risk, panic=panic, latest_news=[item for item in [latest_status, latest_relevant_news] if item])
        if panic.position_risk_stage == PositionRiskStage.observe:
            fp = self._notification_fingerprint("perp-observe", symbol, round(panic.position_drawdown_pct or 0.0, 2))
            notify = self.state.should_emit_notification(f"perp:{symbol}:observe", fp, workflow.panic_notify_cooldown_minutes)
            return AutopilotDecision(phase=AutopilotPhase.observe, notify_user=notify, reason="position_drawdown_requires_attention", product_id=symbol, flow_mode=workflow.entry_mode, signal=signal, risk=risk, panic=panic, latest_news=[item for item in [latest_status, latest_relevant_news] if item])
        if panic.should_exit:
            fp = self._notification_fingerprint("perp-panic", symbol, ",".join(panic.triggers), round(panic.position_drawdown_pct or 0.0, 2))
            notify = self.state.should_emit_notification(f"perp:{symbol}:panic", fp, workflow.panic_notify_cooldown_minutes)
            return AutopilotDecision(phase=AutopilotPhase.panic_exit, notify_user=notify, reason="risk_layer_approved_emergency_exit", product_id=symbol, flow_mode=workflow.entry_mode, signal=signal, risk=risk, panic=panic, latest_news=[item for item in [latest_status, latest_relevant_news] if item], preview={"plan": {"action": "close"}})
        if latest_status and latest_status.severity == "high":
            fp = self._notification_fingerprint("perp-status", symbol, latest_status.severity, latest_status.title)
            notify = self.state.should_emit_notification(f"perp:{symbol}:status", fp, workflow.news_notify_cooldown_minutes)
            return AutopilotDecision(phase=AutopilotPhase.observe, notify_user=notify, reason="exchange_status_requires_observation", product_id=symbol, flow_mode=workflow.entry_mode, signal=signal, risk=risk, panic=panic, latest_news=[latest_status])
        if latest_relevant_news is not None:
            fp = self._notification_fingerprint("perp-news", symbol, latest_relevant_news.title, latest_relevant_news.published_at.isoformat() if latest_relevant_news.published_at else "")
            notify = self.state.should_emit_notification(f"perp:{symbol}:news", fp, workflow.news_notify_cooldown_minutes)
            signal.metadata["strategy_plan_status"] = "blocked"
            signal.metadata["strategy_plan_reason"] = "fresh_relevant_news_requires_observation"
            return AutopilotDecision(phase=AutopilotPhase.observe, notify_user=notify, reason="fresh_relevant_news_requires_observation", product_id=symbol, flow_mode=workflow.entry_mode, signal=signal, risk=risk, panic=panic, latest_news=[latest_relevant_news])

        plan: dict[str, Any] | None = None
        plan_reason = "already_aligned_with_strategy"
        target_notional = strategy_target["target_notional_usd"]
        target_margin = strategy_target["target_margin_usd"]
        max_order = strategy_target["max_order_usd"]
        max_order_margin = strategy_target["max_order_margin_usd"]
        desired_side = strategy_target["desired_side"]
        current_margin = strategy_target["current_margin_usd"]
        try:
            signal_leverage = Decimal(str(signal.leverage))
        except Exception:
            signal_leverage = strategy_target["effective_max_leverage"]
        if signal_leverage <= 0:
            signal_leverage = strategy_target["effective_max_leverage"]
        try:
            position_leverage = Decimal(str(position.leverage)) if position is not None else signal_leverage
        except Exception:
            position_leverage = signal_leverage
        if position_leverage <= 0:
            position_leverage = signal_leverage
        if position is None:
            if desired_side is None or target_notional <= 0:
                plan_reason = "strategy_target_is_flat"
            elif global_breaker_active:
                plan_reason = "panic_global_breaker_active"
            elif coin_cooldown_active:
                plan_reason = "panic_coin_cooldown_active"
            else:
                open_margin = min(target_margin, max_order_margin)
                open_notional = self._margin_to_notional(open_margin, signal_leverage)
                if panic.position_risk_stage in {PositionRiskStage.reduce, PositionRiskStage.exit}:
                    plan_reason = "risk_stage_blocks_new_exposure"
                elif open_notional < min_actionable_notional:
                    plan_reason = "below_exchange_min_notional"
                else:
                    plan_reason = "strategy_target_requires_entry"
                    plan = {
                        "action": "open",
                        "side": desired_side,
                        "notional_usd": str(open_notional),
                        "margin_usd": str(open_margin),
                        "coin": coin.upper(),
                    }
        else:
            if desired_side is None or target_notional <= 0:
                plan_reason = "strategy_target_is_flat"
                plan = {
                    "action": "close",
                    "side": position.side,
                    "notional_usd": str(position.notional_usd),
                    "coin": coin.upper(),
                }
            elif desired_side != position.side:
                reverse_margin = min(target_margin, max_order_margin)
                reverse_notional = self._margin_to_notional(reverse_margin, signal_leverage)
                plan_reason = "strategy_target_requires_side_change"
                close_only = (
                    reverse_notional < min_actionable_notional
                    or panic.position_risk_stage in {PositionRiskStage.reduce, PositionRiskStage.exit}
                    or panic_reentry_block_active
                )
                plan = {
                    "action": "close" if close_only else "flip",
                    "side": position.side if close_only else desired_side,
                    "notional_usd": str(position.notional_usd if close_only else reverse_notional),
                    "margin_usd": str(current_margin if close_only else reverse_margin),
                    "coin": coin.upper(),
                }
                if global_breaker_active:
                    plan_reason = "panic_global_breaker_active"
                elif coin_cooldown_active:
                    plan_reason = "panic_coin_cooldown_active"
            elif current_margin > target_margin:
                reduce_margin = current_margin - target_margin
                reduce_notional = self._margin_to_notional(reduce_margin, position_leverage)
                if reduce_notional < min_actionable_notional:
                    plan_reason = "below_exchange_min_notional"
                else:
                    plan_reason = "strategy_target_requires_reduction"
                    plan = {
                        "action": "reduce",
                        "side": position.side,
                        "notional_usd": str(reduce_notional),
                        "margin_usd": str(reduce_margin),
                        "coin": coin.upper(),
                    }
            else:
                add_margin = min(target_margin - current_margin, max_order_margin)
                add_notional = self._margin_to_notional(add_margin, signal_leverage)
                if add_notional <= 0:
                    plan_reason = "already_aligned_with_strategy"
                elif global_breaker_active:
                    plan_reason = "panic_global_breaker_active"
                elif coin_cooldown_active:
                    plan_reason = "panic_coin_cooldown_active"
                elif panic.position_risk_stage in {PositionRiskStage.reduce, PositionRiskStage.exit}:
                    plan_reason = "risk_stage_blocks_new_exposure"
                elif add_notional < min_actionable_notional:
                    plan_reason = "below_exchange_min_notional"
                else:
                    plan_reason = "strategy_target_requires_add"
                    plan = {
                        "action": "add",
                        "side": position.side,
                        "notional_usd": str(add_notional),
                        "margin_usd": str(add_margin),
                        "coin": coin.upper(),
                    }

        blocked_plan_reasons = {
            "below_exchange_min_notional",
            "risk_stage_blocks_new_exposure",
            "panic_global_breaker_active",
            "panic_coin_cooldown_active",
        }
        signal.metadata["strategy_plan_status"] = "ready" if plan is not None else ("blocked" if plan_reason in blocked_plan_reasons else "idle")
        signal.metadata["strategy_plan_reason"] = plan_reason
        if plan is not None:
            plan["current_notional_usd"] = str(current_position_quote)
            plan["current_margin_usd"] = str(current_margin)
            plan["target_notional_usd"] = str(target_notional)
            plan["target_margin_usd"] = str(target_margin)
            plan["minimum_trade_notional_usd"] = str(minimum_notional)
            if position is not None:
                plan["current_position_leverage"] = str(position_leverage)
            execution_leverage = position_leverage if position is not None and plan["action"] in {"close", "reduce"} else signal_leverage
            plan["execution_leverage"] = str(execution_leverage)
            plan["max_order_notional_usd"] = str(max_order)
            plan["max_order_margin_usd"] = str(max_order_margin)

        if plan is not None:
            fp = self._notification_fingerprint("perp-trade", symbol, plan["action"], plan["side"], plan["notional_usd"], round(signal.confidence, 2))
            notify = self.state.should_emit_notification(f"perp:{symbol}:trade", fp, workflow.signal_notify_cooldown_minutes)
            return AutopilotDecision(phase=AutopilotPhase.trade, notify_user=notify, reason="paper_trade_candidate_ready", product_id=symbol, flow_mode=workflow.entry_mode, signal=signal, risk=risk, panic=panic, latest_news=[item for item in [latest_relevant_news] if item], preview={"plan": plan})

        return AutopilotDecision(phase=AutopilotPhase.heartbeat, notify_user=False, reason="no_action", product_id=symbol, flow_mode=workflow.entry_mode, signal=signal, risk=risk, panic=panic)

    def system_state(self) -> PerpSystemState:
        decisions = [self.autopilot_check(coin) for coin in self.coins()]
        priority = {
            AutopilotPhase.panic_exit: 5,
            AutopilotPhase.trade: 4,
            AutopilotPhase.confirm: 3,
            AutopilotPhase.observe: 2,
            AutopilotPhase.heartbeat: 1,
        }
        if decisions:
            ranked = sorted(
                decisions,
                key=lambda item: (
                    -priority[item.phase],
                    -int(item.notify_user),
                    -(item.signal.confidence if item.signal else 0.0),
                    item.product_id,
                ),
            )
            top_phase = ranked[0].phase
            contenders = [item for item in ranked if item.phase == top_phase]
            primary = contenders[0]
            if len(contenders) > 1:
                cursor_key = f"perp:dispatch:last_primary:{top_phase.value}"
                last_primary = self.state.get_value(cursor_key)
                if last_primary:
                    contender_ids = [item.product_id for item in contenders]
                    if last_primary in contender_ids:
                        primary = contenders[(contender_ids.index(last_primary) + 1) % len(contenders)]
                self.state.set_value(cursor_key, primary.product_id)
        else:
            primary = AutopilotDecision(phase=AutopilotPhase.heartbeat, notify_user=False, reason="no_action", product_id=f"{self.coins()[0]}-PERP", flow_mode=EntryWorkflowMode.auto)
        latest_news: list[NewsItem] = []
        for decision in decisions:
            latest_news.extend(decision.latest_news)
        return PerpSystemState(decisions=decisions, primary=primary, latest_news=latest_news[:5])

    def apply_trade_plan(
        self,
        decision: AutopilotDecision,
        *,
        plan_override: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        plan = plan_override or (((decision.preview or {}).get("plan") if decision.preview else None) or {})
        if not plan:
            return None
        coin = str(plan.get("coin", decision.product_id.split("-")[0])).upper()
        action = str(plan.get("action", ""))
        side = str(plan.get("side", "long")).lower()
        notional = Decimal(str(plan.get("notional_usd", "0")))
        execution_leverage = self._effective_max_leverage()
        if decision.signal is not None:
            try:
                signal_leverage = Decimal(str(decision.signal.leverage))
            except Exception:
                signal_leverage = execution_leverage
            execution_leverage = min(max(signal_leverage, self._effective_min_leverage()), self._effective_max_leverage())
        results: dict[str, Any] = {"coin": coin, "action": action, "results": []}
        any_success = False
        if action == "close":
            close_result = self.engine.close_paper(coin)
            results["results"].append(close_result.model_dump(mode="json"))
            any_success = close_result.success
            if any_success:
                self.reset_position_drawdown_state(coin)
            return results
        if action == "flip":
            close_result = self.engine.close_paper(coin)
            results["results"].append(close_result.model_dump(mode="json"))
            open_result = self.engine.open_paper(side=side, notional_usd=notional, leverage=execution_leverage, coin=coin)
            results["results"].append(open_result.model_dump(mode="json"))
            any_success = close_result.success or open_result.success
            if any_success:
                self.reset_position_drawdown_state(coin)
            return results
        if action == "reduce":
            reduce_result = self.engine.reduce_paper(notional_usd=notional, coin=coin)
            results["results"].append(reduce_result.model_dump(mode="json"))
            any_success = reduce_result.success
            if any_success:
                self.reset_position_drawdown_state(coin)
            return results
        if action == "add":
            add_result = self.engine.add_paper(side=side, notional_usd=notional, leverage=execution_leverage, coin=coin)
            results["results"].append(add_result.model_dump(mode="json"))
            any_success = add_result.success
            if any_success:
                self.reset_position_drawdown_state(coin)
            return results
        if action == "open":
            open_result = self.engine.open_paper(side=side, notional_usd=notional, leverage=execution_leverage, coin=coin)
            results["results"].append(open_result.model_dump(mode="json"))
            any_success = open_result.success
            if any_success:
                self.reset_position_drawdown_state(coin)
            return results
        return None

    def daily_report_payload(self) -> dict[str, Any]:
        portfolio = self.portfolio()
        rows: list[dict[str, Any]] = []
        for coin in self.coins():
            account = self.engine.account(coin)
            signal, risk = self.evaluate_signal(coin)
            rows.append(
                {
                    "coin": coin,
                    "position": account.position.model_dump(mode="json") if account.position else None,
                    "unrealized_pnl_usd": str(account.unrealized_pnl_usd),
                    "signal": signal.model_dump(mode="json"),
                    "risk": risk.model_dump(mode="json"),
                }
            )
        return {
            "portfolio": portfolio.model_dump(mode="json"),
            "coins": rows,
            "strategy": load_current_strategy(),
        }


__all__ = [
    "PerpSupervisor",
    "PerpSystemState",
    "load_current_strategy",
]
