from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ...shared.utils import new_id
from ..memory_assets.service import MemoryAssetsService


class WorkflowTriggerBridge:
    def __init__(self, memory_assets: MemoryAssetsService) -> None:
        self.memory_assets = memory_assets

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
        self.memory_assets.save_asset(
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
        self.memory_assets.save_asset(
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
        self.memory_assets.save_asset(
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

    def record_price_recheck_state(
        self,
        *,
        trace_id: str,
        strategy_id: str,
        price_rechecks: list[dict[str, object]],
    ) -> None:
        """Companion to record_recheck_state for the event-driven (vs
        time-driven) PM wake subscriptions. PriceRecheckMonitor reads back
        the latest record per strategy_id and watches each subscription
        against runtime_bridge_state. Audit trail (one row per submission)
        matches the scheduled_recheck_state pattern.
        """
        self.memory_assets.save_asset(
            asset_type="price_recheck_state",
            asset_id=new_id("price_recheck_state"),
            payload={
                "strategy_id": strategy_id,
                "price_rechecks": price_rechecks,
                "recorded_at_utc": datetime.now(UTC).isoformat(),
            },
            trace_id=trace_id,
            actor_role="system",
            group_key=strategy_id,
        )
