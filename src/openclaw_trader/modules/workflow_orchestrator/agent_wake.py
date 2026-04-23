"""Rule-driven wake monitor for time / silence-based agent heartbeats.

Not a heartbeat in the openclaw-transport sense — this is WO's own timer that
fires an agent turn into an explicit session (typically `agent:<role>:main`)
when a predicate is satisfied.

Predicates supported:
- cron_time: fires at a cron schedule (subset: minute + hour fields, `*` or
  comma-separated integers; other fields must be `*`). Use-case: "guarantee
  PM looks at the book at 01:00 UTC every day".
- max_silence_since: fires when the elapsed time since the last named event
  exceeds a threshold. Currently only `last_strategy_submit` is implemented.
  Use-case: "if PM hasn't published a strategy in 12h, wake them."

Two rules on the same agent are OR'd under `fire_when_any_of`; a shared
per-rule `cooldown_minutes` deduplicates firing when multiple predicates land
in the same scan (e.g. 01:00 UTC after a 13h silence would otherwise trigger
both cron_time and max_silence_since at once).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from typing import Any

from ...shared.infra import EventBus
from ...shared.protocols import EventFactory
from ...shared.utils import new_id
from ..memory_assets.service import MemoryAssetsService
from .agent_dispatch import AgentDispatcher
from .events import MODULE_NAME


# ---------------------------------------------------------------------------
# Rule config — parsed from SystemSettings.agent_wake.rules
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CronTimePredicateConfig:
    kind: str  # always "cron_time"
    expr: str  # "minute hour dom month dow" with our limited parser
    tz: str = "UTC"


@dataclass(frozen=True)
class MaxSilencePredicateConfig:
    kind: str  # always "max_silence_since"
    measure: str  # e.g. "last_strategy_submit"
    hours: float


@dataclass(frozen=True)
class MessageSourceConfig:
    kind: str  # always "cron_job_payload"
    job_id: str


@dataclass(frozen=True)
class AgentWakeRuleConfig:
    name: str
    agent: str
    target_session_key: str
    message_source: MessageSourceConfig
    fire_when_any_of: tuple[CronTimePredicateConfig | MaxSilencePredicateConfig, ...]
    cooldown_minutes: int = 30
    enabled: bool = True
    thinking: str | None = None
    turn_timeout_seconds: int | None = None
    # Fire via `openclaw cron run <job_id>` instead of `openclaw agent
    # --session-id <key>`. Use this when the target_session_key is not
    # `agent:<agent>:main`, because the `openclaw agent` CLI silently
    # falls back to the agent's main session for any --session-id value
    # it doesn't recognize as a UUID. `openclaw cron run` routes through
    # the cron job's own `sessionKey` field, which openclaw DOES honor
    # for non-UUID session keys.
    use_cron_run: bool = False


@dataclass(frozen=True)
class AgentWakeSettings:
    enabled: bool = False
    scan_interval_seconds: int = 60
    rules: tuple[AgentWakeRuleConfig, ...] = ()


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------


class AgentWakeMonitor:
    _STATE_ASSET_ID = "agent_wake_state"
    _STATE_GROUP_KEY = "workflow_orchestrator"
    _EVENT_TYPE = "workflow.agent_wake.fired"

    def __init__(
        self,
        *,
        memory_assets: MemoryAssetsService,
        dispatcher: AgentDispatcher,
        settings: AgentWakeSettings,
        event_bus: EventBus | None = None,
    ) -> None:
        self.memory_assets = memory_assets
        self.dispatcher = dispatcher
        self.settings = settings
        self.event_bus = event_bus
        self._stop = Event()
        self._thread: Thread | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        if not self.settings.enabled or self._thread is not None:
            return
        self._thread = Thread(target=self._loop, name="workflow-orchestrator-agent-wake", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(max(int(self.settings.scan_interval_seconds), 1)):
            try:
                self.scan_once()
            except Exception as exc:  # noqa: BLE001
                # Persist the error so ops can diagnose from the asset alone.
                try:
                    now_iso = datetime.now(UTC).isoformat()
                    state = self._load_state()
                    state["last_scan_at_utc"] = now_iso
                    state["last_error"] = str(exc)
                    state["last_error_at_utc"] = now_iso
                    self._save_state(state)
                except Exception:  # noqa: BLE001
                    pass
                continue

    # ------------------------------------------------------------------
    # Scan
    # ------------------------------------------------------------------
    def scan_once(self, *, now: datetime | None = None) -> dict[str, Any]:
        current = _as_utc(now or datetime.now(UTC))
        state = self._load_state()
        state["last_scan_at_utc"] = current.isoformat()
        state.setdefault("rules", {})
        fire_results: list[dict[str, Any]] = []

        for rule in self.settings.rules:
            if not rule.enabled:
                continue
            rule_state: dict[str, Any] = dict(state["rules"].get(rule.name) or {})
            last_fire_at = _parse_utc(rule_state.get("last_fire_at_utc"))
            last_scan_at = _parse_utc(rule_state.get("_last_eval_at_utc")) or last_fire_at

            # Cooldown check first — if we just fired, skip everything.
            if last_fire_at is not None and _minutes_between(last_fire_at, current) < int(rule.cooldown_minutes):
                rule_state["_last_eval_at_utc"] = current.isoformat()
                state["rules"][rule.name] = rule_state
                continue

            fired_predicate: str | None = None
            for predicate in rule.fire_when_any_of:
                if self._predicate_fired(
                    predicate=predicate,
                    current=current,
                    last_fire_at=last_fire_at,
                    last_eval_at=last_scan_at,
                ):
                    fired_predicate = getattr(predicate, "kind", "unknown")
                    break

            if fired_predicate is None:
                rule_state["_last_eval_at_utc"] = current.isoformat()
                state["rules"][rule.name] = rule_state
                continue

            # Fire: dispatch via one of two paths.
            # - use_cron_run=True (preferred for non-main session_keys):
            #   call `openclaw cron run <job_id>`, which routes through the
            #   cron's own sessionKey (openclaw honors it even for custom
            #   non-UUID keys like `agent:crypto-chief:macro-brief-session`).
            # - use_cron_run=False (legacy path): fetch the message and call
            #   `openclaw agent --session-id <key>`. openclaw silently falls
            #   back to the agent's main session for any non-UUID key, so
            #   this only works when target_session_key == agent:<agent>:main.
            if rule.use_cron_run:
                result = self.dispatcher.run_cron_job_detached(
                    job_id=rule.message_source.job_id
                )
                message = None  # not used on this path
            else:
                message = self.dispatcher.fetch_cron_job_payload_message(
                    job_id=rule.message_source.job_id
                )
                if not message:
                    rule_state["_last_eval_at_utc"] = current.isoformat()
                    rule_state["last_error"] = f"no_payload_message_for_job:{rule.message_source.job_id}"
                    rule_state["last_error_at_utc"] = current.isoformat()
                    state["rules"][rule.name] = rule_state
                    fire_results.append(
                        {"rule": rule.name, "fired": False, "error": "missing_message_source", "predicate": fired_predicate}
                    )
                    continue

                result = self.dispatcher.send_to_session(
                    agent=rule.agent,
                    session_key=rule.target_session_key,
                    message=message,
                    thinking=rule.thinking,
                    turn_timeout_seconds=rule.turn_timeout_seconds,
                )
            rule_state["_last_eval_at_utc"] = current.isoformat()
            rule_state["last_fire_at_utc"] = current.isoformat()
            rule_state["last_fire_predicate"] = fired_predicate
            rule_state["last_fire_pid"] = result.pid
            rule_state["last_fire_ok"] = bool(result.ok)
            rule_state["last_error"] = result.error if not result.ok else None
            rule_state["last_error_at_utc"] = current.isoformat() if not result.ok else None
            state["rules"][rule.name] = rule_state

            fire_results.append(
                {
                    "rule": rule.name,
                    "fired": bool(result.ok),
                    "predicate": fired_predicate,
                    "pid": result.pid,
                    "agent": rule.agent,
                    "session_key": rule.target_session_key,
                }
            )

            if result.ok:
                payload = {
                    "event_id": new_id("agent_wake"),
                    "rule": rule.name,
                    "agent": rule.agent,
                    "session_key": rule.target_session_key,
                    "predicate": fired_predicate,
                    "fired_at_utc": current.isoformat(),
                }
                trace_id = new_id("trace")
                event = EventFactory.build(
                    trace_id=trace_id,
                    event_type=self._EVENT_TYPE,
                    source_module=MODULE_NAME,
                    entity_type="agent_wake_rule",
                    entity_id=rule.name,
                    payload=payload,
                )
                self.memory_assets.append_event(event)
                if self.event_bus is not None:
                    try:
                        self.event_bus.publish(event)
                    except Exception:  # noqa: BLE001
                        pass

        self._save_state(state)
        return {
            "scanned_at_utc": current.isoformat(),
            "fire_count": sum(1 for r in fire_results if r["fired"]),
            "fires": fire_results,
        }

    # ------------------------------------------------------------------
    # Predicate evaluation
    # ------------------------------------------------------------------
    def _predicate_fired(
        self,
        *,
        predicate: CronTimePredicateConfig | MaxSilencePredicateConfig,
        current: datetime,
        last_fire_at: datetime | None,
        last_eval_at: datetime | None,
    ) -> bool:
        kind = getattr(predicate, "kind", "")
        if kind == "cron_time":
            return self._cron_predicate_fired(
                predicate=predicate,  # type: ignore[arg-type]
                current=current,
                last_eval_at=last_eval_at,
            )
        if kind == "max_silence_since":
            return self._silence_predicate_fired(
                predicate=predicate,  # type: ignore[arg-type]
                current=current,
            )
        return False

    def _cron_predicate_fired(
        self,
        *,
        predicate: CronTimePredicateConfig,
        current: datetime,
        last_eval_at: datetime | None,
    ) -> bool:
        # We only evaluate at UTC for now; tz field reserved for future.
        if str(predicate.tz or "UTC").upper() != "UTC":
            # Non-UTC not implemented; skip fire to avoid silent misfire.
            return False
        # Semantics: "fire each calendar candidate exactly once, but only if
        # we actually witnessed the crossing". On the very first scan we have
        # no baseline, so we refuse to fire cron_time and let this scan
        # establish last_eval_at. If a daily candidate was missed during the
        # gap, max_silence_since is the correct safety-net predicate for that
        # case — cron_time should not fabricate a catch-up fire from a cold
        # start, because we have no evidence the previous run happened or not.
        if last_eval_at is None:
            return False
        minutes, hours = _parse_minute_hour_fields(predicate.expr)
        if minutes is None or hours is None:
            return False
        for minute in minutes:
            for hour in hours:
                candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if candidate > current:
                    candidate = candidate - timedelta(days=1)
                if candidate <= last_eval_at:
                    continue
                if candidate <= current:
                    return True
        return False

    def _silence_predicate_fired(
        self,
        *,
        predicate: MaxSilencePredicateConfig,
        current: datetime,
    ) -> bool:
        measure_at = self._resolve_measure_timestamp(predicate.measure)
        if measure_at is None:
            # No prior event recorded — treat as "silence forever" → fire.
            return True
        elapsed_hours = (current - measure_at).total_seconds() / 3600.0
        return elapsed_hours >= float(predicate.hours)

    def _resolve_measure_timestamp(self, measure: str) -> datetime | None:
        if measure == "last_strategy_submit":
            latest = self.memory_assets.latest_asset(asset_type="strategy", actor_role="pm") or self.memory_assets.latest_asset(asset_type="strategy")
            if not latest:
                return None
            return _parse_utc(latest.get("created_at"))
        return None

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------
    def _load_state(self) -> dict[str, Any]:
        asset = self.memory_assets.get_asset(self._STATE_ASSET_ID)
        payload = dict((asset or {}).get("payload") or {})
        return payload

    def _save_state(self, payload: dict[str, Any]) -> None:
        self.memory_assets.save_asset(
            asset_type="agent_wake_state",
            asset_id=self._STATE_ASSET_ID,
            payload=payload,
            actor_role="system",
            group_key=self._STATE_GROUP_KEY,
        )


# ---------------------------------------------------------------------------
# Cron parsing helpers (minimal: minute + hour only)
# ---------------------------------------------------------------------------


def _parse_minute_hour_fields(expr: str) -> tuple[list[int] | None, list[int] | None]:
    """Parse a very limited cron subset.

    Supports:
    - 5-field expression: "minute hour dom month dow"
    - dom / month / dow must all be "*" (else returns (None, None))
    - minute / hour may be "*" or a comma-separated list of integers
    """
    parts = str(expr or "").strip().split()
    if len(parts) != 5:
        return None, None
    minute_field, hour_field, dom, month, dow = parts
    if dom.strip() != "*" or month.strip() != "*" or dow.strip() != "*":
        return None, None
    minutes = _expand_field(minute_field, low=0, high=59)
    hours = _expand_field(hour_field, low=0, high=23)
    if minutes is None or hours is None:
        return None, None
    return minutes, hours


def _expand_field(field_value: str, *, low: int, high: int) -> list[int] | None:
    token = str(field_value or "").strip()
    if not token:
        return None
    if token == "*":
        return list(range(low, high + 1))
    values: list[int] = []
    for item in token.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            number = int(item)
        except ValueError:
            return None
        if number < low or number > high:
            return None
        values.append(number)
    values = sorted(set(values))
    return values or None


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None
    return _as_utc(parsed)


def _minutes_between(earlier: datetime, later: datetime) -> float:
    return (later - earlier).total_seconds() / 60.0
