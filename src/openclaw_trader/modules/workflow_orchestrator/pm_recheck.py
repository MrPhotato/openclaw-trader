from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event, Thread
from typing import Any

from ...shared.infra import EventBus
from ...shared.utils import new_id
from ..memory_assets.service import MemoryAssetsService
from .agent_dispatch import AgentDispatcher, AgentDispatchConfig
from .pm_trigger import record_pm_trigger_event
from .risk_brake import DEFAULT_PM_JOB_ID


@dataclass(frozen=True)
class PMRecheckConfig:
    enabled: bool = False
    pm_job_id: str = DEFAULT_PM_JOB_ID
    pm_session_key: str = "agent:pm:main"
    scan_interval_seconds: int = 30
    cron_subprocess_timeout_seconds: int = 15
    openclaw_bin: str = "openclaw"


class PMRecheckMonitor:
    def __init__(
        self,
        *,
        memory_assets: MemoryAssetsService,
        event_bus: EventBus | None = None,
        config: PMRecheckConfig | None = None,
        agent_dispatcher: AgentDispatcher | None = None,
    ) -> None:
        self.memory_assets = memory_assets
        self.event_bus = event_bus
        self.config = config or PMRecheckConfig()
        self.agent_dispatcher = agent_dispatcher or AgentDispatcher(
            config=AgentDispatchConfig(
                openclaw_bin=self.config.openclaw_bin,
                subprocess_timeout_seconds=self.config.cron_subprocess_timeout_seconds,
            ),
        )
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if not self.config.enabled or self._thread is not None:
            return
        self._thread = Thread(target=self._loop, name="workflow-orchestrator-pm-recheck", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def scan_once(self, *, now: datetime | None = None) -> dict[str, Any]:
        current = _as_utc(now or datetime.now(UTC))
        state = self._load_state()
        due = self.memory_assets.get_due_scheduled_rechecks(now=current)
        current_key = self._current_strategy_key()
        due_keys = [self._recheck_key(item) for item in due]
        state_delta: dict[str, Any] = {}
        if due:
            decision, state_delta = self._dispatch_due_recheck(
                due_item=due[0],
                state=state,
                strategy_key=current_key,
                now=current,
            )
        else:
            decision = {"triggered": False, "scanned_at_utc": current.isoformat()}
        # Single authoritative write at the end of the scan — merges
        # scan metadata with anything the dispatcher wants to persist
        # (e.g. `completed_recheck_keys` for dedupe). Doing two writes
        # caused the stale-snapshot-overwrites-dispatcher-state race
        # we saw in the 08:00 UTC scheduled_recheck storm.
        updated_state = {**dict(state), **state_delta}
        updated_state["last_scan_at_utc"] = current.isoformat()
        if current_key:
            updated_state["last_seen_strategy_key"] = current_key
        if due_keys:
            updated_state["last_due_recheck_keys"] = due_keys
        self._save_state(updated_state)
        return decision

    def _loop(self) -> None:
        while not self._stop.wait(max(int(self.config.scan_interval_seconds), 1)):
            try:
                self.scan_once()
            except Exception:
                continue

    def _dispatch_due_recheck(
        self,
        *,
        due_item: dict[str, Any],
        state: dict[str, Any],
        strategy_key: str | None,
        now: datetime,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        recheck_key = self._recheck_key(due_item)
        completed = {str(item) for item in list(state.get("completed_recheck_keys") or []) if str(item).strip()}
        if recheck_key in completed:
            return (
                {
                    "triggered": False,
                    "reason": "scheduled_recheck",
                    "scheduled_recheck_key": recheck_key,
                    "skipped_reason": "already_dispatched",
                    "scanned_at_utc": now.isoformat(),
                },
                {},
            )

        # Dispatch into PM's main session (not an isolated cron run). We
        # intentionally do NOT gate on "PM already running" any more: if PM
        # is mid-turn, the message simply queues in main session, which is
        # the intended behaviour — PM sees the recheck reason in the same
        # thread as its current context.
        message = self.agent_dispatcher.fetch_cron_job_payload_message(
            job_id=self.config.pm_job_id
        )
        skipped_reason: str | None = None
        dispatched = False
        dispatch_pid: int | None = None
        dispatch_error: str | None = None
        if not message:
            skipped_reason = "missing_pm_payload_message"
        else:
            result = self.agent_dispatcher.send_to_session(
                agent="pm",
                session_key=self.config.pm_session_key,
                message=message,
            )
            dispatched = bool(result.ok)
            dispatch_pid = result.pid
            dispatch_error = result.error
            if not dispatched:
                skipped_reason = f"dispatch_failed:{result.error or 'unknown'}"

        trace_id = new_id("trace")
        payload = {
            "event_id": new_id("pm_trigger"),
            "detected_at_utc": now.isoformat(),
            "trigger_type": "scheduled_recheck",
            "trigger_category": "workflow",
            "reason": "scheduled_recheck",
            "severity": "normal",
            "wake_source": "workflow_orchestrator",
            "claimable": bool(dispatched),
            "strategy_id": due_item.get("strategy_id"),
            "revision_number": due_item.get("revision_number"),
            "strategy_key": strategy_key,
            "recheck_at_utc": due_item.get("recheck_at_utc"),
            "scope": due_item.get("scope"),
            "recheck_reason": due_item.get("reason"),
            "scheduled_recheck_key": recheck_key,
            "dispatched": dispatched,
            "skipped_reason": skipped_reason,
            "dispatch_target": "agent:pm:main",
            "dispatch_pid": dispatch_pid,
            "dispatch_error": dispatch_error,
        }
        record_pm_trigger_event(
            memory_assets=self.memory_assets,
            event_bus=self.event_bus,
            trace_id=trace_id,
            payload=payload,
            metadata={"trigger_type": "scheduled_recheck"},
        )
        state_delta: dict[str, Any] = {}
        if dispatched:
            completed_list = list(completed)
            completed_list.append(recheck_key)
            state_delta = {
                "last_trigger_at_utc": now.isoformat(),
                "completed_recheck_keys": completed_list[-64:],
                "last_pm_trigger_event_id": payload["event_id"],
            }
            if strategy_key:
                state_delta["last_seen_strategy_key"] = strategy_key
        payload["triggered"] = True
        return payload, state_delta

    def _current_strategy_key(self) -> str | None:
        latest_strategy = self.memory_assets.get_latest_strategy()
        payload = dict((latest_strategy or {}).get("payload") or {})
        strategy_id = str(payload.get("strategy_id") or "").strip()
        revision = payload.get("revision_number")
        if not strategy_id or revision is None:
            return None
        return f"{strategy_id}:{revision}"

    def _load_state(self) -> dict[str, Any]:
        asset = self.memory_assets.get_asset("pm_recheck_state")
        return dict((asset or {}).get("payload") or {})

    def _save_state(self, payload: dict[str, Any]) -> None:
        self.memory_assets.save_asset(
            asset_type="pm_recheck_state",
            asset_id="pm_recheck_state",
            payload=payload,
            actor_role="system",
            group_key="pm",
        )

    @staticmethod
    def _recheck_key(item: dict[str, Any]) -> str:
        strategy_id = str(item.get("strategy_id") or "").strip()
        recheck_at = str(item.get("recheck_at_utc") or "").strip()
        scope = str(item.get("scope") or "").strip()
        reason = str(item.get("reason") or "").strip()
        return f"{strategy_id}|{recheck_at}|{scope}|{reason}"

def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
