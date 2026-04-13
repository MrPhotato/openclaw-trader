from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event, Thread
from typing import Any

from ...shared.infra import EventBus
from ...shared.protocols import EventFactory
from ...shared.utils import new_id
from ..agent_gateway.service import AgentGatewayService
from ..memory_assets.service import MemoryAssetsService
from .events import MODULE_NAME
from .rt_trigger import OpenClawCronRunner


@dataclass(frozen=True)
class RetroPrepConfig:
    enabled: bool = False
    scan_interval_seconds: int = 60
    prep_hour_utc: int = 22
    prep_minute_utc: int = 40
    chief_job_id: str = "6b0359fe-f8e4-4f82-9671-3b9c28c49299"
    cron_subprocess_timeout_seconds: int = 15
    openclaw_bin: str = "openclaw"


class RetroPrepMonitor:
    _STATE_ASSET_ID = "retro_prep_state"
    _STATE_GROUP_KEY = "crypto_chief"
    _EVENT_TYPE = "workflow.retro_prep.updated"
    _RETRO_BRIEF_ROLES = ("pm", "risk_trader", "macro_event_analyst")

    def __init__(
        self,
        *,
        memory_assets: MemoryAssetsService,
        agent_gateway: AgentGatewayService,
        event_bus: EventBus | None = None,
        config: RetroPrepConfig | None = None,
        cron_runner: OpenClawCronRunner | None = None,
    ) -> None:
        self.memory_assets = memory_assets
        self.agent_gateway = agent_gateway
        self.event_bus = event_bus
        self.config = config or RetroPrepConfig()
        self.cron_runner = cron_runner or OpenClawCronRunner(
            openclaw_bin=self.config.openclaw_bin,
            timeout_seconds=self.config.cron_subprocess_timeout_seconds,
        )
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if not self.config.enabled or self._thread is not None:
            return
        self._thread = Thread(target=self._loop, name="workflow-orchestrator-retro-prep", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def scan_once(self, *, now: datetime | None = None, force: bool = False) -> dict[str, Any]:
        current = _as_utc(now or datetime.now(UTC))
        state = self._load_state()
        state["last_scan_at_utc"] = current.isoformat()
        if not force and not self._within_prep_window(current):
            self._save_state(state)
            return {
                "triggered": False,
                "scanned_at_utc": current.isoformat(),
                "reason": "outside_prep_window",
            }

        case_day_utc = current.date().isoformat()
        retro_case = self.memory_assets.latest_retro_case(case_day_utc=case_day_utc)
        case_id = str((retro_case or {}).get("case_id") or "")
        existing_briefs = self.memory_assets.get_retro_briefs(case_id=case_id) if case_id else []
        existing_roles = {str(item.get("agent_role") or "") for item in existing_briefs}
        missing_roles = [role for role in self._RETRO_BRIEF_ROLES if role not in existing_roles]
        if retro_case is not None and not missing_roles:
            dispatch_result = self._dispatch_chief_when_ready(
                case_id=case_id,
                state=state,
                now=current,
            )
            state.update(
                {
                    "last_prepared_case_day_utc": case_day_utc,
                    "last_case_id": case_id,
                    "last_prepared_at_utc": current.isoformat(),
                    "last_status": "ready",
                    "missing_roles": [],
                }
            )
            self._save_state(state)
            return {
                "triggered": bool(dispatch_result.get("chief_dispatched")),
                "scanned_at_utc": current.isoformat(),
                "status": "ready",
                "case_id": case_id,
                "retro_brief_count": len(existing_briefs),
                **dispatch_result,
            }

        trace_id = new_id("trace")
        try:
            prepared_cycle = self.agent_gateway.prepare_retro_cycle_from_runtime_bridge(
                trace_id=trace_id,
                trigger_type="daily_retro",
                force_new_case=retro_case is None,
            )
        except Exception as exc:
            state.update(
                {
                    "last_status": "error",
                    "last_error": str(exc),
                    "last_error_at_utc": current.isoformat(),
                }
            )
            self._save_state(state)
            return {
                "triggered": True,
                "scanned_at_utc": current.isoformat(),
                "status": "error",
                "error": str(exc),
            }

        prepared_case = dict(prepared_cycle.get("retro_case") or {})
        prepared_briefs = list(prepared_cycle.get("retro_briefs") or [])
        prepared_roles = {str(item.get("agent_role") or "") for item in prepared_briefs}
        pending_roles = [role for role in self._RETRO_BRIEF_ROLES if role not in prepared_roles]
        payload = {
            "event_id": new_id("retro_prep"),
            "prepared_at_utc": current.isoformat(),
            "case_day_utc": case_day_utc,
            "case_id": str(prepared_case.get("case_id") or ""),
            "retro_brief_count": len(prepared_briefs),
            "prepared_roles": list(prepared_roles),
            "pending_roles": pending_roles,
            "status": "ready" if not pending_roles else "partial",
        }
        event = EventFactory.build(
            trace_id=trace_id,
            event_type=self._EVENT_TYPE,
            source_module=MODULE_NAME,
            entity_type="retro_case",
            entity_id=str(payload["case_id"] or payload["event_id"]),
            payload=payload,
        )
        self.memory_assets.append_event(event)
        if self.event_bus is not None:
            try:
                self.event_bus.publish(event)
            except Exception:
                pass
        state.update(
            {
                "last_prepared_case_day_utc": case_day_utc,
                "last_case_id": payload["case_id"],
                "last_prepared_at_utc": current.isoformat(),
                "last_status": payload["status"],
                "missing_roles": pending_roles,
                "last_error": None,
            }
        )
        dispatch_result = self._dispatch_chief_when_ready(
            case_id=str(payload["case_id"] or ""),
            state=state,
            now=current,
        )
        self._save_state(state)
        return {
            "triggered": True,
            "scanned_at_utc": current.isoformat(),
            **payload,
            **dispatch_result,
        }

    def _loop(self) -> None:
        while not self._stop.wait(max(int(self.config.scan_interval_seconds), 1)):
            try:
                self.scan_once()
            except Exception:
                continue

    def _within_prep_window(self, current: datetime) -> bool:
        scheduled_at = current.replace(
            hour=int(self.config.prep_hour_utc),
            minute=int(self.config.prep_minute_utc),
            second=0,
            microsecond=0,
        )
        return current >= scheduled_at

    def _load_state(self) -> dict[str, Any]:
        asset = self.memory_assets.get_asset(self._STATE_ASSET_ID)
        return dict((asset or {}).get("payload") or {})

    def _save_state(self, payload: dict[str, Any]) -> None:
        self.memory_assets.save_asset(
            asset_type="retro_prep_state",
            asset_id=self._STATE_ASSET_ID,
            payload=payload,
            actor_role="system",
            group_key=self._STATE_GROUP_KEY,
        )

    def _dispatch_chief_when_ready(
        self,
        *,
        case_id: str,
        state: dict[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        if not case_id:
            return {
                "chief_dispatched": False,
                "chief_dispatch_status": "missing_case_id",
            }

        if self._latest_completed_case_id() == case_id:
            state.update(
                {
                    "last_dispatched_case_id": case_id,
                    "last_dispatched_at_utc": now.isoformat(),
                    "last_dispatch_status": "already_completed",
                }
            )
            return {
                "chief_dispatched": False,
                "chief_dispatch_status": "already_completed",
                "chief_job_id": self.config.chief_job_id,
            }

        if str(state.get("last_dispatched_case_id") or "") == case_id:
            return {
                "chief_dispatched": False,
                "chief_dispatch_status": "already_dispatched",
                "chief_job_id": self.config.chief_job_id,
            }

        if self.cron_runner.is_running(job_id=self.config.chief_job_id):
            state.update(
                {
                    "last_dispatch_status": "chief_running",
                    "last_dispatch_checked_at_utc": now.isoformat(),
                }
            )
            return {
                "chief_dispatched": False,
                "chief_dispatch_status": "chief_running",
                "chief_job_id": self.config.chief_job_id,
            }

        if hasattr(self.cron_runner, "run_now_detached"):
            spawn_result = self.cron_runner.run_now_detached(job_id=self.config.chief_job_id)
            state.update(
                {
                    "last_dispatched_case_id": case_id if spawn_result.ok else state.get("last_dispatched_case_id"),
                    "last_dispatched_at_utc": now.isoformat(),
                    "last_dispatch_status": "dispatched" if spawn_result.ok else "dispatch_error",
                    "last_dispatch_pid": spawn_result.pid,
                    "last_dispatch_stderr": spawn_result.error or "",
                    "last_dispatch_stdout": "",
                }
            )
            return {
                "chief_dispatched": bool(spawn_result.ok),
                "chief_dispatch_status": "dispatched" if spawn_result.ok else "dispatch_error",
                "chief_job_id": self.config.chief_job_id,
                "chief_dispatch_pid": spawn_result.pid,
            }

        run_result = self.cron_runner.run_now(job_id=self.config.chief_job_id)
        state.update(
            {
                "last_dispatched_case_id": case_id if run_result.ok else state.get("last_dispatched_case_id"),
                "last_dispatched_at_utc": now.isoformat(),
                "last_dispatch_status": "dispatched" if run_result.ok else "dispatch_error",
                "last_dispatch_stdout": run_result.stdout or "",
                "last_dispatch_stderr": run_result.stderr or "",
            }
        )
        return {
            "chief_dispatched": bool(run_result.ok),
            "chief_dispatch_status": "dispatched" if run_result.ok else "dispatch_error",
            "chief_job_id": self.config.chief_job_id,
            "chief_dispatch_returncode": run_result.returncode,
        }

    def _latest_completed_case_id(self) -> str:
        latest = self.memory_assets.latest_asset(asset_type="chief_retro")
        payload = dict((latest or {}).get("payload") or {})
        return str(payload.get("case_id") or "")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
