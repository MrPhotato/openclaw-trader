from __future__ import annotations

from ..models import ManualTriggerCommand
from .base import WorkflowEventRecorder, WorkflowModuleServices


class ControlWorkflowHandler(WorkflowEventRecorder):
    def __init__(self, services: WorkflowModuleServices) -> None:
        super().__init__(services)

    def can_handle(self, command: ManualTriggerCommand) -> bool:
        return command.command_type.value in {
            "pause_workflow",
            "resume_workflow",
            "sync_news",
            "retrain_models",
            "emit_daily_report",
            "replay_window",
            "reset_agent_sessions",
        }

    def handle(self, command: ManualTriggerCommand, *, workflow_id: str, trace_id: str) -> dict:
        if command.command_type.value in {"pause_workflow", "resume_workflow"}:
            return {"status": command.command_type.value, "workflow_id": workflow_id, "trace_id": trace_id}
        if command.command_type.value == "sync_news":
            digest = self.services.news_events.sync()
            self.record_events([self.services.news_events.build_sync_event(trace_id=trace_id, events=digest)])
            return {"news_events": [item.model_dump(mode="json") for item in digest]}
        if command.command_type.value == "retrain_models":
            status = self.services.quant_intelligence.retrain_models(command.scope.get("coins"))
            self.record_events([self.services.quant_intelligence.build_retrain_event(trace_id=trace_id, payload=status)])
            return {"retrained": status}
        if command.command_type.value == "emit_daily_report":
            return {"daily_report": self.services.replay_frontend.build_daily_report()}
        if command.command_type.value == "replay_window":
            replay = self.services.replay_frontend.query(
                trace_id=command.params.get("trace_id"),
                module=command.params.get("module"),
            )
            return {"replay": replay.model_dump(mode="json")}
        if command.command_type.value == "reset_agent_sessions":
            reset_results: list[dict[str, object]] = []
            reset_events = []
            for agent_role in ("pm", "risk_trader", "macro_event_analyst", "crypto_chief"):
                requested_session_id = self.services.agent_gateway.session_id_for_role(agent_role)
                reset_result = self.services.agent_gateway.reset_agent_session(
                    agent_role=agent_role,
                    session_id=requested_session_id,
                    reset_command="/new",
                )
                effective_session_id = str(reset_result.get("effective_session_id") or requested_session_id)
                reset_results.append(reset_result)
                self.services.state_memory.save_agent_session(
                    agent_role=agent_role,
                    session_id=effective_session_id,
                    status="active",
                    last_reset_command="/new",
                )
                reset_events.append(
                    self.services.agent_gateway.build_session_reset_event(
                        trace_id=trace_id,
                        agent_role=agent_role,
                        session_id=effective_session_id,
                        result=reset_result,
                    )
                )
            if reset_events:
                self.record_events(reset_events)
            return {"reset_command": "/new", "reset_results": reset_results}
        raise ValueError(f"unsupported control command: {command.command_type.value}")
