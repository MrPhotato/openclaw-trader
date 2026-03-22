from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ...shared.utils import new_id
from ..state_memory.service import StateMemoryService


class WorkflowTriggerBridge:
    def __init__(self, state_memory: StateMemoryService) -> None:
        self.state_memory = state_memory

    def get_trigger_context(
        self,
        *,
        agent_role: str,
        trigger_type: str,
        params: dict[str, object] | None = None,
    ) -> dict[str, object]:
        payload = dict(params or {})
        return {
            "agent_role": agent_role,
            "trigger_type": trigger_type,
            "cadence_source": str(payload.get("cadence_source") or "").strip() or None,
            "cadence_label": str(payload.get("cadence_label") or "").strip() or None,
            "requested_at_utc": datetime.now(UTC).isoformat(),
            "reason": str(payload.get("reason") or trigger_type).strip() or trigger_type,
            "metadata": payload,
        }

    def record_runtime_pack_issued(
        self,
        *,
        input_id: str,
        trace_id: str,
        agent_role: str,
        trigger_context: dict[str, object],
        expires_at_utc: str,
    ) -> None:
        self.state_memory.save_asset(
            asset_type="runtime_pack_issue",
            asset_id=new_id("runtime_pack_issue"),
            payload={
                "input_id": input_id,
                "agent_role": agent_role,
                "trigger_context": trigger_context,
                "expires_at_utc": expires_at_utc,
            },
            trace_id=trace_id,
            actor_role="system",
            group_key=agent_role,
            metadata={"input_id": input_id},
        )

    def record_runtime_pack_consumed(
        self,
        *,
        input_id: str,
        trace_id: str,
        agent_role: str,
        submission_kind: str,
    ) -> None:
        self.state_memory.save_asset(
            asset_type="runtime_pack_consumed",
            asset_id=new_id("runtime_pack_consumed"),
            payload={
                "input_id": input_id,
                "agent_role": agent_role,
                "submission_kind": submission_kind,
                "consumed_at_utc": datetime.now(UTC).isoformat(),
            },
            trace_id=trace_id,
            actor_role="system",
            group_key=input_id,
            metadata={"submission_kind": submission_kind},
        )

    def record_recheck_state(
        self,
        *,
        trace_id: str,
        strategy_id: str,
        rechecks: list[dict[str, object]],
    ) -> None:
        self.state_memory.save_asset(
            asset_type="scheduled_recheck_state",
            asset_id=new_id("scheduled_recheck_state"),
            payload={
                "strategy_id": strategy_id,
                "rechecks": rechecks,
                "recorded_at_utc": datetime.now(UTC).isoformat(),
            },
            trace_id=trace_id,
            actor_role="system",
            group_key=strategy_id,
        )
