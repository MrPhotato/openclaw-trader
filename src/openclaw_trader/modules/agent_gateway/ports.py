from __future__ import annotations

from typing import Protocol

from .models import AgentReply, AgentTask


class AgentRunner(Protocol):
    def run(self, task: AgentTask) -> AgentReply: ...


class AgentSessionController(Protocol):
    def reset(self, *, agent_role: str, session_id: str, reset_command: str = "/new") -> dict[str, object]: ...


class TriggerContextBridge(Protocol):
    def get_trigger_context(
        self,
        *,
        agent_role: str,
        trigger_type: str,
        params: dict[str, object] | None = None,
    ) -> dict[str, object]: ...

    def record_runtime_pack_issued(
        self,
        *,
        input_id: str,
        trace_id: str,
        agent_role: str,
        trigger_context: dict[str, object],
        expires_at_utc: str,
    ) -> None: ...

    def record_runtime_pack_consumed(
        self,
        *,
        input_id: str,
        trace_id: str,
        agent_role: str,
        submission_kind: str,
    ) -> None: ...

    def record_recheck_state(
        self,
        *,
        trace_id: str,
        strategy_id: str,
        rechecks: list[dict[str, object]],
    ) -> None: ...
