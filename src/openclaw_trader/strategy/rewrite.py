from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..config import StrategyConfig
from ..models import AutopilotDecision, AutopilotPhase, NewsItem
from ..state import StateStore
from .formatting import _parse_iso_datetime

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

def _normalize_scheduled_rechecks(
    raw_items: list[Any] | None,
    *,
    now: datetime,
    current_items: list[dict[str, Any]] | None = None,
    drop_past: bool = True,
) -> list[dict[str, Any]]:
    items = raw_items if raw_items is not None else current_items or []
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    cutoff = now.astimezone(UTC)
    for item in items:
        if not isinstance(item, dict):
            continue
        fingerprint = str(item.get("fingerprint", "")).strip()
        if not fingerprint:
            continue
        event_at = _parse_iso_datetime(item.get("event_at"))
        run_at = _parse_iso_datetime(item.get("run_at"))
        if event_at is None or run_at is None:
            continue
        if drop_past and run_at < cutoff:
            continue
        reason = str(item.get("reason", "")).strip()
        key = (fingerprint, run_at.isoformat())
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "fingerprint": fingerprint,
                "event_at": event_at.isoformat(),
                "run_at": run_at.isoformat(),
                "reason": reason,
            }
        )
    normalized.sort(key=lambda item: item["run_at"])
    return normalized

def _strategy_daily_hours(strategy: StrategyConfig) -> list[int]:
    raw_hours = strategy.daily_hours or [strategy.daily_hour]
    normalized = sorted(
        {
            int(hour)
            for hour in raw_hours
            if isinstance(hour, (int, float)) and 0 <= int(hour) <= 23
        }
    )
    if normalized:
        return normalized
    legacy_hour = int(strategy.daily_hour)
    return [min(max(legacy_hour, 0), 23)]

def current_strategy_schedule_slot(strategy: StrategyConfig, now: datetime) -> str | None:
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(strategy.timezone)
    local_now = now.astimezone(tz)
    due_hours = [hour for hour in _strategy_daily_hours(strategy) if local_now.hour >= hour]
    if not due_hours:
        return None
    return f"{local_now.date().isoformat()}@{max(due_hours):02d}"

def clear_strategy_pending_regime_shift(state: StateStore) -> None:
    state.delete_value(STRATEGY_PENDING_REGIME_SHIFT_KEY)

def mark_strategy_regime_shift_rewrite(state: StateStore, now: datetime) -> None:
    state.set_value(STRATEGY_LAST_REGIME_SHIFT_REWRITE_AT_KEY, now.astimezone(UTC).isoformat(), now=now)

def strategy_due_today(
    state: StateStore,
    strategy: StrategyConfig,
    now: datetime,
) -> bool:
    slot_key = current_strategy_schedule_slot(strategy, now)
    if slot_key is None:
        return False
    return state.get_value("strategy:last_strategy_slot") != slot_key


def routine_refresh_due(
    state: StateStore,
    strategy: StrategyConfig,
    now: datetime,
) -> bool:
    slot_key = current_strategy_schedule_slot(strategy, now)
    if slot_key is None:
        return False
    local_date = now.astimezone(ZoneInfo(strategy.timezone)).date().isoformat()
    return state.get_value("strategy:last_strategy_date") != local_date

def _strategy_rewrite_layers(strategy: StrategyConfig) -> set[str]:
    return {layer.lower() for layer in strategy.rewrite_layers}

def _strategy_rewrite_severities(strategy: StrategyConfig) -> set[str]:
    return {severity.lower() for severity in strategy.rewrite_severities}

def _strategy_news_fingerprint(item: NewsItem) -> str:
    return f"{item.source}|{item.title}|{item.url}"

def _exchange_status_rewrite_relevant(item: NewsItem) -> bool:
    if item.severity.lower() == "high":
        return True
    haystack = " ".join(
        [
            item.source,
            item.title,
            item.url,
            item.summary or "",
            *item.tags,
        ]
    ).lower()
    return any(token in haystack for token in _EXCHANGE_STATUS_STRATEGY_REWRITE_KEYWORDS)

def _news_item_matches_strategy_rewrite(strategy: StrategyConfig, item: NewsItem) -> bool:
    if item.layer.lower() not in _strategy_rewrite_layers(strategy):
        return False
    if item.severity.lower() not in _strategy_rewrite_severities(strategy):
        return False
    if item.layer.lower() == "exchange-status" and not _exchange_status_rewrite_relevant(item):
        return False
    return True

def _news_item_triggers_strategy_rewrite(
    state: StateStore,
    strategy: StrategyConfig,
    item: NewsItem,
) -> bool:
    if not _news_item_matches_strategy_rewrite(strategy, item):
        return False
    return state.get_value("strategy:last_news_fingerprint") != _strategy_news_fingerprint(item)

def strategy_rewrite_due_by_news(
    state: StateStore,
    strategy: StrategyConfig,
    news_items: list[NewsItem],
    now: datetime,
    *,
    bypass_cooldown: bool = False,
) -> bool:
    cooldown_raw = state.get_value("strategy:last_updated_at")
    if cooldown_raw and not bypass_cooldown:
        last_updated = datetime.fromisoformat(cooldown_raw)
        if last_updated.tzinfo is None:
            last_updated = last_updated.replace(tzinfo=UTC)
        delta_minutes = (now - last_updated).total_seconds() / 60
        if delta_minutes < strategy.rewrite_cooldown_minutes:
            return False
    for item in news_items:
        if _news_item_triggers_strategy_rewrite(state, strategy, item):
            return True
    return False

def strategy_rewrite_reason(
    state: StateStore,
    strategy: StrategyConfig,
    *,
    current_strategy: dict[str, Any] | None,
    decision: AutopilotDecision,
    now: datetime,
) -> str | None:
    news_items = decision.latest_news
    bypass_cooldown = any(
        item.severity.lower() == "high" and _news_item_matches_strategy_rewrite(strategy, item)
        for item in news_items
    ) or decision.phase == AutopilotPhase.panic_exit
    if strategy_rewrite_due_by_news(
        state,
        strategy,
        news_items,
        now,
        bypass_cooldown=bypass_cooldown,
    ):
        for item in news_items:
            if _news_item_triggers_strategy_rewrite(state, strategy, item):
                return f"major_news:{item.source}"

    current_market_regime = str((current_strategy or {}).get("market_regime") or "").strip().lower()
    signal_market_regime = str((decision.signal.metadata or {}).get("regime") or "").strip().lower() if decision.signal else ""
    regime_shift_ready = False
    if signal_market_regime and current_market_regime and signal_market_regime != current_market_regime:
        now_utc = now.astimezone(UTC)
        raw_pending = state.get_value(STRATEGY_PENDING_REGIME_SHIFT_KEY)
        pending: dict[str, Any] = {}
        if raw_pending:
            try:
                pending = json.loads(raw_pending)
            except Exception:
                pending = {}
        expected = {
            "from": current_market_regime,
            "to": signal_market_regime,
        }
        first_seen_at = now_utc
        observed_count = 1
        if pending.get("from") == expected["from"] and pending.get("to") == expected["to"]:
            parsed_first_seen = _parse_iso_datetime(pending.get("first_seen_at"))
            if parsed_first_seen is not None:
                first_seen_at = parsed_first_seen
            try:
                observed_count = max(int(pending.get("count", 1)), 1) + 1
            except Exception:
                observed_count = 2
        state.set_value(
            STRATEGY_PENDING_REGIME_SHIFT_KEY,
            json.dumps(
                {
                    "from": expected["from"],
                    "to": expected["to"],
                    "first_seen_at": first_seen_at.isoformat(),
                    "observed_at": now_utc.isoformat(),
                    "count": observed_count,
                }
            ),
            now=now,
        )
        rounds_required = max(int(strategy.regime_shift_confirmation_rounds), 1)
        minutes_required = max(int(strategy.regime_shift_confirmation_minutes), 0)
        regime_shift_ready = (
            observed_count >= rounds_required
            and now_utc - first_seen_at >= timedelta(minutes=minutes_required)
        )
    else:
        clear_strategy_pending_regime_shift(state)

    cooldown_raw = state.get_value("strategy:last_updated_at")
    cooldown_elapsed = True
    if cooldown_raw and not bypass_cooldown:
        last_updated = datetime.fromisoformat(cooldown_raw)
        if last_updated.tzinfo is None:
            last_updated = last_updated.replace(tzinfo=UTC)
        cooldown_elapsed = (now - last_updated).total_seconds() / 60 >= strategy.rewrite_cooldown_minutes
    if not cooldown_elapsed and not bypass_cooldown:
        return None

    if decision.phase == AutopilotPhase.panic_exit:
        return "risk_shift:panic_exit"

    if regime_shift_ready:
        regime_cooldown_raw = state.get_value(STRATEGY_LAST_REGIME_SHIFT_REWRITE_AT_KEY)
        if regime_cooldown_raw:
            last_regime_shift = datetime.fromisoformat(regime_cooldown_raw)
            if last_regime_shift.tzinfo is None:
                last_regime_shift = last_regime_shift.replace(tzinfo=UTC)
            delta_minutes = (now.astimezone(UTC) - last_regime_shift.astimezone(UTC)).total_seconds() / 60
            if delta_minutes < max(strategy.regime_shift_rewrite_cooldown_minutes, 0):
                return None
        return f"regime_shift:{signal_market_regime}"

    return None

def scheduled_recheck_reason(
    state: StateStore,
    current_strategy: dict[str, Any] | None,
    *,
    now: datetime,
) -> tuple[str, str] | None:
    scheduled_rechecks = (current_strategy or {}).get("scheduled_rechecks") if isinstance(current_strategy, dict) else None
    if not isinstance(scheduled_rechecks, list):
        return None
    normalized = _normalize_scheduled_rechecks(
        scheduled_rechecks,
        now=now,
        current_items=None,
        drop_past=False,
    )
    for item in normalized:
        run_at = _parse_iso_datetime(item.get("run_at"))
        if run_at is None or run_at > now.astimezone(UTC):
            continue
        fingerprint = str(item.get("fingerprint", "")).strip()
        if not fingerprint:
            continue
        mark_key = f"strategy:scheduled_recheck:{fingerprint}|{run_at.isoformat()}"
        if state.get_value(mark_key):
            continue
        return (f"scheduled_recheck:{fingerprint}", mark_key)
    return None
