from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import UTC, datetime
from threading import Event, Lock, Thread

from ...shared.infra import EventBus
from ...shared.protocols import EventFactory
from ...shared.utils import new_id
from ..memory_assets.models import WorkflowStateRef
from ..memory_assets.service import MemoryAssetsService
from .events import (
    EVENT_COMMAND_ACCEPTED,
    EVENT_EXTERNAL_CADENCE_DELIVERED,
    EVENT_WORKFLOW_COMPLETED,
    EVENT_WORKFLOW_DEGRADED,
    EVENT_WORKFLOW_FAILED,
    EVENT_WORKFLOW_RUNNING,
    MODULE_NAME,
)
from .handlers import WorkflowCommandExecutor
from .models import CommandType, ExternalCadenceWakeup, ManualTriggerCommand, WorkflowCommandReceipt, WorkflowStateRecord
from .pm_recheck import PMRecheckMonitor
from .retro_prep import RetroPrepMonitor
from .risk_brake import RiskBrakeMonitor
from .rt_trigger import RTTriggerMonitor


class WorkflowOrchestratorService:
    _LEGACY_MARKET_COMMANDS = {
        CommandType.dispatch_once,
        CommandType.run_pm,
        CommandType.run_rt,
        CommandType.run_mea,
        CommandType.refresh_strategy,
        CommandType.rerun_trade_review,
    }

    def __init__(
        self,
        *,
        memory_assets: MemoryAssetsService,
        event_bus: EventBus,
        executor: WorkflowCommandExecutor,
        run_in_background: bool = True,
        max_background_workers: int = 4,
        enable_daily_session_reset: bool = False,
        daily_session_reset_hour_utc: int = 0,
        daily_session_reset_minute_utc: int = 30,
        rt_trigger_monitor: RTTriggerMonitor | None = None,
        pm_recheck_monitor: PMRecheckMonitor | None = None,
        risk_brake_monitor: RiskBrakeMonitor | None = None,
        retro_prep_monitor: RetroPrepMonitor | None = None,
    ) -> None:
        self.memory_assets = memory_assets
        self.event_bus = event_bus
        self.executor = executor
        self.run_in_background = run_in_background
        self._future_lock = Lock()
        self._futures_by_trace: dict[str, Future[None]] = {}
        self._background_executor = ThreadPoolExecutor(
            max_workers=max_background_workers,
            thread_name_prefix="workflow-orchestrator",
        )
        self._scheduler_stop = Event()
        self._daily_session_reset_hour_utc = daily_session_reset_hour_utc
        self._daily_session_reset_minute_utc = daily_session_reset_minute_utc
        self._daily_reset_thread: Thread | None = None
        self._rt_trigger_monitor = rt_trigger_monitor
        self._last_daily_reset_date: str | None = None
        if enable_daily_session_reset:
            self._daily_reset_thread = Thread(
                target=self._daily_reset_loop,
                name="workflow-orchestrator-daily-reset",
                daemon=True,
            )
            self._daily_reset_thread.start()
        if self._rt_trigger_monitor is not None:
            self._rt_trigger_monitor.start()
        self._pm_recheck_monitor = pm_recheck_monitor
        if self._pm_recheck_monitor is not None:
            self._pm_recheck_monitor.start()
        self._risk_brake_monitor = risk_brake_monitor
        if self._risk_brake_monitor is not None:
            self._risk_brake_monitor.start()
        self._retro_prep_monitor = retro_prep_monitor
        if self._retro_prep_monitor is not None:
            self._retro_prep_monitor.start()

    def submit_command(self, command: ManualTriggerCommand) -> WorkflowCommandReceipt:
        blocked_reason = self._blocked_reason(command)
        if blocked_reason is not None:
            return WorkflowCommandReceipt(
                command_id=command.command_id,
                accepted=False,
                reason=blocked_reason,
            )
        existing = self.memory_assets.get_workflow_by_command(command.command_id)
        if existing is not None:
            return WorkflowCommandReceipt(
                command_id=command.command_id,
                accepted=False,
                reason="duplicate_command",
                workflow_id=existing.workflow_id,
                trace_id=existing.trace_id,
            )
        workflow_id = new_id("wf")
        trace_id = new_id("trace")
        workflow = WorkflowStateRef(
            workflow_id=workflow_id,
            trace_id=trace_id,
            state="accepted",
            reason=command.command_type.value,
            last_transition_at=datetime.now(UTC),
        )
        self.memory_assets.save_workflow(command.command_id, workflow, command.model_dump(mode="json"))
        accepted = EventFactory.build(
            trace_id=trace_id,
            workflow_id=workflow_id,
            event_type=EVENT_COMMAND_ACCEPTED,
            source_module=MODULE_NAME,
            entity_type="workflow_command",
            entity_id=command.command_id,
            payload=command.model_dump(mode="json"),
        )
        self.memory_assets.append_event(accepted)
        self._publish_best_effort(accepted)
        cadence_event = self._record_external_cadence(command=command, workflow_id=workflow_id, trace_id=trace_id)
        if cadence_event is not None:
            self.memory_assets.append_event(cadence_event)
            self._publish_best_effort(cadence_event)
        if self.run_in_background:
            future = self._background_executor.submit(
                self._run,
                command=command,
                workflow_id=workflow_id,
                trace_id=trace_id,
            )
            with self._future_lock:
                self._futures_by_trace[trace_id] = future
            future.add_done_callback(lambda completed, trace=trace_id: self._forget_future(trace, completed))
        else:
            self._run(command=command, workflow_id=workflow_id, trace_id=trace_id)
        return WorkflowCommandReceipt(
            command_id=command.command_id,
            accepted=True,
            reason="accepted",
            workflow_id=workflow_id,
            trace_id=trace_id,
        )

    def _blocked_reason(self, command: ManualTriggerCommand) -> str | None:
        if command.command_type in self._LEGACY_MARKET_COMMANDS:
            return "legacy_market_workflow_disabled_use_agent_cron"
        return None

    def _record_external_cadence(self, *, command: ManualTriggerCommand, workflow_id: str, trace_id: str):
        cadence_source = str(command.params.get("cadence_source") or "").strip()
        cadence_label = str(command.params.get("cadence_label") or "").strip()
        agent_role = str(command.params.get("agent_role") or "").strip()
        if not cadence_source or not cadence_label or not agent_role:
            return None
        wakeup = ExternalCadenceWakeup(
            agent_role=agent_role,
            source=cadence_source,
            cadence_label=cadence_label,
        )
        self.memory_assets.save_asset(
            asset_type="external_cadence_wakeup",
            payload=wakeup.model_dump(mode="json"),
            trace_id=trace_id,
            actor_role="system",
            group_key=f"{agent_role}:{cadence_label}",
            metadata={"workflow_id": workflow_id},
        )
        return EventFactory.build(
            trace_id=trace_id,
            workflow_id=workflow_id,
            event_type=EVENT_EXTERNAL_CADENCE_DELIVERED,
            source_module=MODULE_NAME,
            entity_type="external_cadence_wakeup",
            entity_id=f"{agent_role}:{cadence_label}",
            payload=wakeup.model_dump(mode="json"),
        )

    def _transition(self, *, command_id: str, workflow_id: str, trace_id: str, state: str, reason: str, payload: dict) -> None:
        workflow = WorkflowStateRef(
            workflow_id=workflow_id,
            trace_id=trace_id,
            state=state,
            reason=reason,
            last_transition_at=datetime.now(UTC),
        )
        self.memory_assets.save_workflow(command_id, workflow, payload)

    def _run(self, *, command: ManualTriggerCommand, workflow_id: str, trace_id: str) -> None:
        running = EventFactory.build(
            trace_id=trace_id,
            workflow_id=workflow_id,
            event_type=EVENT_WORKFLOW_RUNNING,
            source_module=MODULE_NAME,
            entity_type="workflow_state",
            entity_id=workflow_id,
            payload={"state": "running", "command_type": command.command_type.value},
        )
        self.memory_assets.append_event(running)
        self._publish_best_effort(running)
        self._transition(
            command_id=command.command_id,
            workflow_id=workflow_id,
            trace_id=trace_id,
            state="running",
            reason=command.command_type.value,
            payload=command.model_dump(mode="json"),
        )
        try:
            if command.command_type == CommandType.run_retro_prep:
                if self._retro_prep_monitor is None:
                    raise RuntimeError("retro_prep_monitor_disabled")
                result = self._retro_prep_monitor.scan_once(force=True)
            else:
                result = self.executor.handle(command, workflow_id=workflow_id, trace_id=trace_id)
        except Exception as exc:  # pragma: no cover - defensive
            failed = EventFactory.build(
                trace_id=trace_id,
                workflow_id=workflow_id,
                event_type=EVENT_WORKFLOW_FAILED,
                source_module=MODULE_NAME,
                entity_type="workflow_state",
                entity_id=workflow_id,
                payload={"state": "failed", "error": str(exc)},
            )
            self.memory_assets.append_event(failed)
            self._publish_best_effort(failed)
            self._transition(
                command_id=command.command_id,
                workflow_id=workflow_id,
                trace_id=trace_id,
                state="failed",
                reason=str(exc),
                payload={"error": str(exc)},
            )
            return
        event_type = EVENT_WORKFLOW_DEGRADED if result.get("degraded") else EVENT_WORKFLOW_COMPLETED
        final_state = "degraded" if result.get("degraded") else "completed"
        completed = EventFactory.build(
            trace_id=trace_id,
            workflow_id=workflow_id,
            event_type=event_type,
            source_module=MODULE_NAME,
            entity_type="workflow_state",
            entity_id=workflow_id,
            payload={"state": final_state, "result": result},
        )
        self.memory_assets.append_event(completed)
        self._publish_best_effort(completed)
        self._transition(
            command_id=command.command_id,
            workflow_id=workflow_id,
            trace_id=trace_id,
            state=final_state,
            reason=command.command_type.value,
            payload=result,
        )

    def _publish_best_effort(self, event) -> None:
        try:
            self.event_bus.publish(event)
        except Exception:
            return None

    def get_workflow(self, trace_id: str) -> WorkflowStateRecord | None:
        workflow = self.memory_assets.get_workflow(trace_id)
        if workflow is None:
            return None
        return WorkflowStateRecord(
            workflow_id=workflow.workflow_id,
            trace_id=workflow.trace_id,
            state=workflow.state,
            reason=workflow.reason,
            last_transition_at=workflow.last_transition_at,
        )

    def wait_for_workflow(self, trace_id: str, *, timeout_seconds: float = 10.0) -> WorkflowStateRecord | None:
        with self._future_lock:
            future = self._futures_by_trace.get(trace_id)
        if future is not None:
            try:
                future.result(timeout=timeout_seconds)
            except FutureTimeoutError:
                return self.get_workflow(trace_id)
        return self.get_workflow(trace_id)

    def close(self) -> None:
        self._scheduler_stop.set()
        if self._rt_trigger_monitor is not None:
            self._rt_trigger_monitor.stop()
        if self._pm_recheck_monitor is not None:
            self._pm_recheck_monitor.stop()
        if self._risk_brake_monitor is not None:
            self._risk_brake_monitor.stop()
        if self._retro_prep_monitor is not None:
            self._retro_prep_monitor.stop()
        if self._daily_reset_thread is not None:
            self._daily_reset_thread.join(timeout=1.0)
        self._background_executor.shutdown(wait=False, cancel_futures=False)

    def _forget_future(self, trace_id: str, future: Future[None]) -> None:
        with self._future_lock:
            current = self._futures_by_trace.get(trace_id)
            if current is future:
                self._futures_by_trace.pop(trace_id, None)

    def _daily_reset_loop(self) -> None:
        while not self._scheduler_stop.is_set():
            now = datetime.now(UTC)
            reset_date = now.date().isoformat()
            if self._should_issue_daily_reset(now=now, reset_date=reset_date):
                receipt = self.submit_command(
                    ManualTriggerCommand(
                        command_id=f"cmd-reset-agent-sessions-{reset_date}",
                        command_type=CommandType.reset_agent_sessions,
                        initiator="workflow_orchestrator",
                        params={"trigger_type": "daily_session_reset"},
                    )
                )
                if receipt.accepted or receipt.reason == "duplicate_command":
                    self._last_daily_reset_date = reset_date
            self._scheduler_stop.wait(20.0)

    def _should_issue_daily_reset(self, *, now: datetime, reset_date: str) -> bool:
        if self._last_daily_reset_date == reset_date:
            return False
        scheduled_at = now.replace(
            hour=self._daily_session_reset_hour_utc,
            minute=self._daily_session_reset_minute_utc,
            second=0,
            microsecond=0,
        )
        return now >= scheduled_at
