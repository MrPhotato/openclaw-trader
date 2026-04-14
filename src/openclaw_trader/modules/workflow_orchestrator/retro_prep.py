from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
    brief_deadline_minutes: int = 15
    chief_window_minutes: int = 15
    chief_job_id: str = "6b0359fe-f8e4-4f82-9671-3b9c28c49299"
    cron_subprocess_timeout_seconds: int = 15
    openclaw_bin: str = "openclaw"


class RetroPrepMonitor:
    _STATE_ASSET_ID = "retro_prep_state"
    _STATE_GROUP_KEY = "crypto_chief"
    _EVENT_TYPE = "workflow.retro_prep.updated"
    _RETRO_BRIEF_ROLES = ("pm", "risk_trader", "macro_event_analyst")
    _RETRO_LEARNING_ROLES = ("pm", "risk_trader", "macro_event_analyst", "crypto_chief")

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
        cycle_state = self._ensure_cycle_state(now=current, trade_day_utc=case_day_utc)
        learning_updates = self._scan_pending_learning_directives(now=current)
        retro_case = self._retro_case_for_cycle(cycle_state=cycle_state, trade_day_utc=case_day_utc)
        case_id = str((retro_case or {}).get("case_id") or "")
        runtime_inputs: dict[str, Any] | None = None
        if retro_case is None:
            trace_id = new_id("trace")
            try:
                prepared_cycle = self.agent_gateway.ensure_retro_case_from_runtime_bridge(
                    trace_id=trace_id,
                    trigger_type="daily_retro",
                    case_day_utc=case_day_utc,
                    cycle_id=str(cycle_state.get("cycle_id") or ""),
                    force_new_case=True,
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
            retro_case = dict(prepared_cycle.get("retro_case") or {})
            runtime_inputs = dict(prepared_cycle.get("runtime_inputs") or {})
        case_id = str((retro_case or {}).get("case_id") or "")
        cycle_id = str((retro_case or {}).get("cycle_id") or cycle_state.get("cycle_id") or "")
        existing_retro = self._latest_chief_retro_for_case(case_id=case_id)
        if existing_retro is not None:
            cycle_state, learning_status = self._sync_learning_directives(
                cycle_state=cycle_state,
                retro_case=retro_case or {},
                chief_retro=existing_retro,
                now=current,
            )
            learning_updates.extend(self._scan_pending_learning_directives(now=current))
            if learning_status == "failed":
                state.update(
                    {
                        "last_prepared_case_day_utc": case_day_utc,
                        "last_case_id": case_id,
                        "last_prepared_at_utc": current.isoformat(),
                        "last_status": "failed",
                        "missing_roles": [],
                        "last_dispatch_status": "already_completed",
                        "learning_updates": learning_updates,
                    }
                )
                self._save_state(state)
                return {
                    "triggered": False,
                    "scanned_at_utc": current.isoformat(),
                    "status": "failed",
                    "case_id": case_id,
                    "retro_brief_count": len(self.memory_assets.get_retro_briefs(case_id=case_id, cycle_id=cycle_id or None)),
                    "chief_dispatched": False,
                    "chief_dispatch_status": "already_completed",
                    "chief_job_id": self.config.chief_job_id,
                }
            final_state = "degraded" if str(cycle_state.get("state") or "") == "degraded" else "completed"
            cycle_state = self._save_cycle_state(
                cycle_state=cycle_state,
                trace_id=None,
                updates={
                    "state": final_state,
                    "retro_case_id": case_id or None,
                    "chief_retro_id": str(existing_retro.get("retro_id") or existing_retro.get("asset_id") or "") or None,
                    "missing_brief_roles": [],
                },
            )
            state.update(
                {
                    "last_prepared_case_day_utc": case_day_utc,
                    "last_case_id": case_id,
                    "last_prepared_at_utc": current.isoformat(),
                    "last_status": final_state,
                    "missing_roles": [],
                    "last_dispatch_status": "already_completed",
                    "learning_updates": learning_updates,
                }
            )
            self._save_state(state)
            return {
                "triggered": False,
                "scanned_at_utc": current.isoformat(),
                "status": final_state,
                "case_id": case_id,
                "retro_brief_count": len(self.memory_assets.get_retro_briefs(case_id=case_id, cycle_id=cycle_id or None)),
                "chief_dispatched": False,
                "chief_dispatch_status": "already_completed",
                "chief_job_id": self.config.chief_job_id,
            }

        existing_briefs = self.memory_assets.get_retro_briefs(case_id=case_id, cycle_id=cycle_id or None) if case_id else []
        existing_roles = {str(item.get("agent_role") or "") for item in existing_briefs}
        pending_roles = [role for role in self._RETRO_BRIEF_ROLES if role not in existing_roles]
        brief_deadline_passed = self._deadline_passed(cycle_state.get("brief_deadline_utc"), current)
        brief_errors: dict[str, str] = {}
        trace_id: str | None = None
        if pending_roles and not brief_deadline_passed:
            trace_id = new_id("trace")
            if runtime_inputs is None:
                prepared_cycle = self.agent_gateway.ensure_retro_case_from_runtime_bridge(
                    trace_id=trace_id,
                    trigger_type="daily_retro",
                    case_day_utc=case_day_utc,
                    cycle_id=cycle_id or str(cycle_state.get("cycle_id") or ""),
                    force_new_case=False,
                )
                runtime_inputs = dict(prepared_cycle.get("runtime_inputs") or {})
            for agent_role in list(pending_roles):
                if agent_role not in runtime_inputs:
                    brief_errors[agent_role] = "missing_runtime_input"
                    continue
                try:
                    self.agent_gateway.run_retro_brief_submission(
                        trace_id=trace_id,
                        agent_role=agent_role,
                        runtime_input=runtime_inputs[agent_role],
                        retro_case=retro_case,
                    )
                except Exception as exc:
                    brief_errors[agent_role] = str(exc)
            existing_briefs = self.memory_assets.get_retro_briefs(case_id=case_id, cycle_id=cycle_id or None)
            existing_roles = {str(item.get("agent_role") or "") for item in existing_briefs}
            pending_roles = [role for role in self._RETRO_BRIEF_ROLES if role not in existing_roles]

        status = "partial"
        cycle_updates = {
            "retro_case_id": case_id or None,
            "ready_brief_roles": sorted(existing_roles),
            "missing_brief_roles": pending_roles,
            "chief_retro_id": None,
        }
        if pending_roles:
            if brief_deadline_passed:
                status = "degraded"
                cycle_updates.update(
                    {
                        "state": "degraded",
                        "degraded_reason": "missing_briefs",
                    }
                )
            else:
                cycle_updates.update(
                    {
                        "state": "brief_collection",
                        "degraded_reason": None,
                    }
                )
        else:
            status = "ready"
            cycle_updates.update(
                {
                    "state": "chief_pending",
                    "degraded_reason": None,
                }
            )
        cycle_state = self._save_cycle_state(
            cycle_state=cycle_state,
            trace_id=trace_id,
            updates=cycle_updates,
        )
        payload = {
            "event_id": new_id("retro_prep"),
            "prepared_at_utc": current.isoformat(),
            "case_day_utc": case_day_utc,
            "case_id": case_id,
            "retro_brief_count": len(existing_briefs),
            "prepared_roles": sorted(existing_roles),
            "pending_roles": pending_roles,
            "status": status,
        }
        event = EventFactory.build(
            trace_id=trace_id or new_id("trace"),
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
                "brief_errors": brief_errors,
            }
        )
        dispatch_result = self._dispatch_chief_when_ready(case_id=str(payload["case_id"] or ""), cycle_state=cycle_state, state=state, now=current)
        self._save_state(state)
        return {
            "triggered": True if payload["status"] in {"ready", "degraded"} or brief_errors or payload["retro_brief_count"] else False,
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

    def _ensure_cycle_state(self, *, now: datetime, trade_day_utc: str) -> dict[str, Any]:
        cycle_state = self.memory_assets.latest_retro_cycle_state(trade_day_utc=trade_day_utc)
        if cycle_state is not None:
            return cycle_state
        brief_deadline = now + timedelta(minutes=max(int(self.config.brief_deadline_minutes), 1))
        chief_deadline = brief_deadline + timedelta(minutes=max(int(self.config.chief_window_minutes), 1))
        return self.memory_assets.materialize_retro_cycle_state(
            trace_id=new_id("trace"),
            authored_payload={
                "trade_day_utc": trade_day_utc,
                "state": "case_created",
                "started_at_utc": now.isoformat(),
                "brief_deadline_utc": brief_deadline.isoformat(),
                "chief_deadline_utc": chief_deadline.isoformat(),
                "ready_brief_roles": [],
                "missing_brief_roles": list(self._RETRO_BRIEF_ROLES),
            },
            actor_role="system",
            group_key=trade_day_utc,
        )

    def _save_cycle_state(
        self,
        *,
        cycle_state: dict[str, Any],
        trace_id: str | None,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        payload = dict(cycle_state)
        payload.update(updates)
        saved = self.memory_assets.save_retro_cycle_state(
            trace_id=trace_id,
            cycle_id=str(cycle_state.get("cycle_id") or ""),
            payload=payload,
            actor_role="system",
        )
        return {
            "asset_id": str(saved.get("cycle_id") or ""),
            **saved,
        }

    def _dispatch_chief_when_ready(
        self,
        *,
        case_id: str,
        cycle_state: dict[str, Any],
        state: dict[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        if not case_id:
            return {
                "chief_dispatched": False,
                "chief_dispatch_status": "missing_case_id",
            }
        cycle_phase = str(cycle_state.get("state") or "").strip()
        if cycle_phase not in {"chief_pending", "degraded"}:
            return {
                "chief_dispatched": False,
                "chief_dispatch_status": "not_ready",
                "chief_job_id": self.config.chief_job_id,
            }
        if self._latest_chief_retro_for_case(case_id=case_id) is not None:
            state.update(
                {
                    "last_dispatched_case_id": case_id,
                    "last_dispatched_at_utc": now.isoformat(),
                    "last_dispatch_status": "already_completed",
                }
            )
            self._save_cycle_state(
                cycle_state=cycle_state,
                trace_id=None,
                updates={"state": "completed", "chief_dispatch_status": "completed"},
            )
            return {
                "chief_dispatched": False,
                "chief_dispatch_status": "already_completed",
                "chief_job_id": self.config.chief_job_id,
            }
        if str(cycle_state.get("chief_dispatch_status") or "") in {"dispatched", "chief_running"}:
            state.update(
                {
                    "last_dispatched_case_id": case_id,
                    "last_dispatched_at_utc": now.isoformat(),
                    "last_dispatch_status": "already_dispatched",
                }
            )
            return {
                "chief_dispatched": False,
                "chief_dispatch_status": "already_dispatched",
                "chief_job_id": self.config.chief_job_id,
            }

        if self.cron_runner.is_running(job_id=self.config.chief_job_id):
            self._save_cycle_state(
                cycle_state=cycle_state,
                trace_id=None,
                updates={"chief_dispatch_status": "chief_running"},
            )
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
            self._save_cycle_state(
                cycle_state=cycle_state,
                trace_id=None,
                updates={"chief_dispatch_status": "dispatched" if spawn_result.ok else "dispatch_error"},
            )
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
        self._save_cycle_state(
            cycle_state=cycle_state,
            trace_id=None,
            updates={"chief_dispatch_status": "dispatched" if run_result.ok else "dispatch_error"},
        )
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

    def _retro_case_for_cycle(self, *, cycle_state: dict[str, Any], trade_day_utc: str) -> dict[str, Any] | None:
        case_id = str(cycle_state.get("retro_case_id") or "").strip()
        if case_id:
            retro_case = self.memory_assets.get_retro_case(case_id=case_id)
            if retro_case is not None:
                return retro_case
        return self.memory_assets.latest_retro_case(case_day_utc=trade_day_utc)

    def _latest_chief_retro_for_case(self, *, case_id: str) -> dict[str, Any] | None:
        if not case_id:
            return None
        for asset in self.memory_assets.recent_assets(asset_type="chief_retro", actor_role="crypto_chief", limit=10):
            payload = dict(asset.get("payload") or {})
            if str(payload.get("case_id") or "") != case_id:
                continue
            return {
                "trace_id": asset.get("trace_id"),
                "group_key": asset.get("group_key"),
                "source_ref": asset.get("source_ref"),
                "asset_id": asset.get("asset_id"),
                **payload,
            }
        return None

    def _sync_learning_directives(
        self,
        *,
        cycle_state: dict[str, Any],
        retro_case: dict[str, Any],
        chief_retro: dict[str, Any],
        now: datetime,
    ) -> tuple[dict[str, Any], str]:
        case_id = str(retro_case.get("case_id") or chief_retro.get("case_id") or "").strip()
        cycle_id = str(retro_case.get("cycle_id") or cycle_state.get("cycle_id") or chief_retro.get("cycle_id") or "").strip()
        existing = self.memory_assets.get_learning_directives(case_id=case_id, cycle_id=cycle_id or None)
        if existing:
            return cycle_state, "completed"
        directives = self._normalize_learning_directives(chief_retro.get("learning_directives"))
        directives_by_role = {str(item.get("agent_role") or ""): item for item in directives}
        missing_roles = [role for role in self._RETRO_LEARNING_ROLES if role not in directives_by_role]
        if missing_roles:
            updated_cycle_state = self._save_cycle_state(
                cycle_state=cycle_state,
                trace_id=None,
                updates={
                    "state": "failed",
                    "degraded_reason": f"missing_learning_directives:{','.join(missing_roles)}",
                },
            )
            return updated_cycle_state, "failed"
        created: list[dict[str, Any]] = []
        issued_at_utc = chief_retro.get("created_at_utc") or chief_retro.get("created_at") or now.isoformat()
        for agent_role in self._RETRO_LEARNING_ROLES:
            directive = directives_by_role[agent_role]
            learning_path = self._learning_path_for_role(agent_role)
            created.append(
                self.memory_assets.materialize_learning_directive(
                    trace_id=str(chief_retro.get("trace_id") or new_id("trace")),
                    case_id=case_id,
                    cycle_id=cycle_id or None,
                    agent_role=agent_role,
                    session_key=self._session_key_for_role(agent_role),
                    learning_path=learning_path,
                    actor_role="system",
                    source_ref=str(chief_retro.get("asset_id") or ""),
                    authored_payload={
                        "directive": directive["directive"],
                        "rationale": directive["rationale"],
                        "issued_at_utc": issued_at_utc,
                        "baseline_fingerprint": self._learning_file_fingerprint(learning_path),
                        "completion_state": "pending",
                    },
                )
            )
        self._save_chief_retro_learning_ids(chief_retro=chief_retro, directive_ids=[item["directive_id"] for item in created])
        return cycle_state, "completed"

    def _save_chief_retro_learning_ids(self, *, chief_retro: dict[str, Any], directive_ids: list[str]) -> None:
        asset_id = str(chief_retro.get("asset_id") or "")
        if not asset_id:
            return
        payload = dict(chief_retro)
        payload.pop("asset_id", None)
        payload.pop("trace_id", None)
        payload.pop("group_key", None)
        payload.pop("source_ref", None)
        payload["learning_directive_ids"] = directive_ids
        self.memory_assets.save_asset(
            asset_type="chief_retro",
            asset_id=asset_id,
            payload=payload,
            trace_id=str(chief_retro.get("trace_id") or new_id("trace")),
            actor_role="crypto_chief",
            group_key=str(chief_retro.get("group_key") or chief_retro.get("meeting_id") or asset_id),
            source_ref=str(chief_retro.get("source_ref") or "") or None,
        )

    def _scan_pending_learning_directives(self, *, now: datetime) -> list[dict[str, Any]]:
        updates: list[dict[str, Any]] = []
        for directive in self.memory_assets.get_learning_directives(limit=100):
            if str(directive.get("completion_state") or "pending") != "pending":
                continue
            baseline = dict(directive.get("baseline_fingerprint") or {})
            current_state = self._learning_file_fingerprint(str(directive.get("learning_path") or ""))
            if self._learning_file_changed(baseline=baseline, current_state=current_state):
                completion_state = "completed"
                completed_at_utc = now.isoformat()
            elif self._learning_file_became_stale(baseline=baseline, current_state=current_state):
                completion_state = "stale"
                completed_at_utc = None
            else:
                continue
            updated = self.memory_assets.save_learning_directive(
                trace_id=None,
                directive_id=str(directive.get("directive_id") or directive.get("asset_id") or ""),
                actor_role="system",
                source_ref=str(directive.get("source_ref") or "") or None,
                payload={
                    **directive,
                    "completion_state": completion_state,
                    "completed_at_utc": completed_at_utc,
                },
            )
            updates.append(updated)
        return updates

    @staticmethod
    def _normalize_learning_directives(payload: Any) -> list[dict[str, str]]:
        directives: list[dict[str, str]] = []
        for item in list(payload or []):
            if not isinstance(item, dict):
                continue
            agent_role = str(item.get("agent_role") or "").strip()
            directive = str(item.get("directive") or "").strip()
            rationale = str(item.get("rationale") or "").strip()
            if not agent_role or not directive or not rationale:
                continue
            directives.append(
                {
                    "agent_role": agent_role,
                    "directive": directive,
                    "rationale": rationale,
                }
            )
        return directives

    def _learning_path_for_role(self, agent_role: str) -> str:
        return str(
            self.agent_gateway.learning_path_by_role.get(agent_role)
            or self.agent_gateway._DEFAULT_LEARNING_PATH_BY_ROLE.get(agent_role, "")
        )

    def _session_key_for_role(self, agent_role: str) -> str:
        agent_name = self.agent_gateway.agent_name_by_role.get(agent_role) or self.agent_gateway._DEFAULT_AGENT_NAME_BY_ROLE.get(agent_role, agent_role)
        return f"agent:{agent_name}:main"

    @staticmethod
    def _learning_file_fingerprint(learning_path: str) -> dict[str, Any]:
        path = Path(learning_path)
        if not path.exists():
            return {
                "exists": False,
                "mtime_ns": None,
                "size_bytes": 0,
                "content_sha256": None,
            }
        try:
            content = path.read_bytes()
        except OSError:
            content = b""
        stat = path.stat()
        return {
            "exists": True,
            "mtime_ns": stat.st_mtime_ns,
            "size_bytes": stat.st_size,
            "content_sha256": hashlib.sha256(content).hexdigest(),
        }

    @staticmethod
    def _learning_file_changed(*, baseline: dict[str, Any], current_state: dict[str, Any]) -> bool:
        if not bool(current_state.get("exists")) or int(current_state.get("size_bytes") or 0) <= 0:
            return False
        if not bool(baseline.get("exists")):
            return True
        return any(
            current_state.get(key) != baseline.get(key)
            for key in ("mtime_ns", "size_bytes", "content_sha256")
        )

    @staticmethod
    def _learning_file_became_stale(*, baseline: dict[str, Any], current_state: dict[str, Any]) -> bool:
        if not baseline:
            return False
        if bool(baseline.get("exists")) and not bool(current_state.get("exists")):
            return True
        if any(current_state.get(key) != baseline.get(key) for key in ("exists", "size_bytes", "content_sha256")):
            return int(current_state.get("size_bytes") or 0) <= 0
        return False

    @staticmethod
    def _deadline_passed(raw_timestamp: Any, now: datetime) -> bool:
        deadline = _parse_utc(raw_timestamp)
        if deadline is None:
            return False
        return now > deadline


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    return _as_utc(parsed)
