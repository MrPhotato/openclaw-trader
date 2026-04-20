"""Event-driven macro_brief refresh detector — spec 014 FR-011 / NFR-007.

Pure decision function (+ thin stateful cooldown). The actual Chief dispatch
stays in `AgentWakeMonitor` / `AgentDispatcher` — this module only answers
"given (news_events, latest_macro_brief, recent_forced_refreshes), should
we force-refresh right now?". Keeps the logic unit-testable without wiring
a thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


_HIGH_IMPACT_MACRO_CATEGORIES = frozenset(
    {
        "monetary_policy",
        "macro_data",
        "geopolitical",
    }
)


@dataclass(frozen=True)
class MacroBriefForceRefreshDecision:
    should_refresh: bool
    reason: str
    triggered_by_event_id: str | None = None
    event_detected_at_utc: str | None = None
    event_category: str | None = None


def decide_macro_brief_force_refresh(
    *,
    news_events: list[dict[str, Any]],
    latest_macro_brief: dict[str, Any] | None,
    recent_forced_refreshes_today: list[dict[str, Any]],
    now: datetime | None = None,
    refresh_window_minutes: int = 30,
    daily_force_refresh_cap: int = 2,
) -> MacroBriefForceRefreshDecision:
    """Return a refresh decision for a single scan tick.

    Logic (matches spec 014 FR-011 / NFR-007):
    - Look for news_events with impact_level=high AND category in
      {monetary_policy, macro_data, geopolitical} that were detected within
      the last `refresh_window_minutes` AND are strictly newer than the
      latest brief's generated_at_utc.
    - Cap at `daily_force_refresh_cap` forced refreshes per UTC day to avoid
      headline storms.
    """
    current = _as_utc(now or datetime.now(UTC))
    day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    forced_today = [
        item for item in (recent_forced_refreshes_today or [])
        if _as_utc_optional(item.get("refreshed_at_utc")) and _as_utc_optional(item.get("refreshed_at_utc")) >= day_start
    ]
    if len(forced_today) >= max(int(daily_force_refresh_cap), 1):
        return MacroBriefForceRefreshDecision(
            should_refresh=False,
            reason="daily_force_refresh_cap_reached",
        )

    brief_generated_at = _as_utc_optional((latest_macro_brief or {}).get("generated_at_utc"))
    cutoff = current - timedelta(minutes=max(int(refresh_window_minutes), 1))

    for event in news_events or []:
        if not isinstance(event, dict):
            continue
        impact = str(event.get("impact_level") or "").strip().lower()
        if impact != "high":
            continue
        category = str(event.get("category") or "").strip().lower()
        if category not in _HIGH_IMPACT_MACRO_CATEGORIES:
            continue
        detected_at = _as_utc_optional(event.get("detected_at_utc") or event.get("published_at"))
        if detected_at is None:
            continue
        if detected_at < cutoff:
            # Event is older than the window — either we already refreshed or
            # the event is historical context, not a live force-refresh signal.
            continue
        if brief_generated_at is not None and detected_at <= brief_generated_at:
            # Brief already saw this event.
            continue
        return MacroBriefForceRefreshDecision(
            should_refresh=True,
            reason="high_impact_macro_event",
            triggered_by_event_id=str(event.get("event_id") or ""),
            event_detected_at_utc=detected_at.isoformat(),
            event_category=category,
        )
    return MacroBriefForceRefreshDecision(
        should_refresh=False,
        reason="no_triggering_event",
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _as_utc_optional(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    return _as_utc(parsed)
