from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from ..config import RuntimeConfig
from ..state import StateStore


def last_llm_trigger_at(state: StateStore) -> datetime | None:
    raw = state.get_value("dispatch:last_llm_trigger_at")
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def mark_llm_trigger(state: StateStore, now: datetime) -> None:
    state.set_value("dispatch:last_llm_trigger_at", now.astimezone(UTC).isoformat())


def daily_report_due(state: StateStore, runtime: RuntimeConfig, now: datetime) -> bool:
    tz = ZoneInfo(runtime.dispatch.daily_report_timezone)
    local_now = now.astimezone(tz)
    report_date = local_now.date().isoformat()
    last_report_date = state.get_value("dispatch:last_daily_report_date")
    if last_report_date == report_date:
        return False
    return local_now.hour >= runtime.dispatch.daily_report_hour


def mark_daily_report(state: StateStore, runtime: RuntimeConfig, now: datetime) -> None:
    tz = ZoneInfo(runtime.dispatch.daily_report_timezone)
    state.set_value("dispatch:last_daily_report_date", now.astimezone(tz).date().isoformat())


def fallback_due(state: StateStore, runtime: RuntimeConfig, now: datetime) -> bool:
    last_trigger = last_llm_trigger_at(state)
    if last_trigger is None:
        return True
    return now - last_trigger >= timedelta(minutes=runtime.dispatch.llm_fallback_minutes)


def mark_strategy(
    state: StateStore,
    runtime: RuntimeConfig,
    now: datetime,
    *,
    fingerprint: str | None = None,
    reason: str | None = None,
    current_strategy_schedule_slot_fn,
    mark_strategy_regime_shift_rewrite_fn,
    clear_strategy_pending_regime_shift_fn,
) -> None:
    state.set_value("strategy:last_updated_at", now.astimezone(UTC).isoformat())
    tz = ZoneInfo(runtime.strategy.timezone)
    state.set_value("strategy:last_strategy_date", now.astimezone(tz).date().isoformat())
    slot_key = current_strategy_schedule_slot_fn(runtime.strategy, now)
    if slot_key:
        state.set_value("strategy:last_strategy_slot", slot_key, now=now)
    if fingerprint:
        state.set_value("strategy:last_news_fingerprint", fingerprint)
    if str(reason or "").strip().lower().startswith("regime_shift:"):
        mark_strategy_regime_shift_rewrite_fn(state, now)
    clear_strategy_pending_regime_shift_fn(state)


def mark_scheduled_recheck(state: StateStore, mark_key: str | None, now: datetime) -> None:
    if not mark_key:
        return
    state.set_value(mark_key, now.astimezone(UTC).isoformat(), now=now)


def daily_strategy_slot_lock_key(slot_key: str, *, prefix: str) -> str:
    return f"{prefix}{slot_key}"


def acquire_daily_strategy_slot_lock(
    state: StateStore,
    runtime: RuntimeConfig,
    slot_key: str,
    now: datetime,
    *,
    prefix: str,
) -> bool:
    ttl_seconds = max(
        300,
        int(runtime.dispatch.timeout_seconds + runtime.dispatch.process_timeout_grace_seconds + 60),
    )
    return state.acquire_timed_lock(
        daily_strategy_slot_lock_key(slot_key, prefix=prefix),
        ttl_seconds=ttl_seconds,
        now=now,
    )


def release_daily_strategy_slot_lock(state: StateStore, slot_key: str, *, prefix: str) -> None:
    state.delete_value(daily_strategy_slot_lock_key(slot_key, prefix=prefix))
