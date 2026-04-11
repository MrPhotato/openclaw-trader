from __future__ import annotations

from typing import Any

from ...shared.infra import EventBus
from ...shared.protocols import EventFactory
from ...shared.utils import new_id
from ..memory_assets.service import MemoryAssetsService
from .events import EVENT_PM_TRIGGER_DETECTED, MODULE_NAME


def record_pm_trigger_event(
    *,
    memory_assets: MemoryAssetsService,
    event_bus: EventBus | None,
    trace_id: str,
    payload: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = dict(payload)
    normalized["event_id"] = str(normalized.get("event_id") or new_id("pm_trigger"))
    normalized["trigger_category"] = str(
        normalized.get("trigger_category")
        or ("workflow" if str(normalized.get("trigger_type") or "") in {"scheduled_recheck", "risk_brake"} else "unknown")
    ).strip() or "unknown"
    normalized["wake_source"] = str(
        normalized.get("wake_source")
        or ("workflow_orchestrator" if normalized["trigger_category"] == "workflow" else "unknown")
    ).strip() or "unknown"
    memory_assets.save_asset(
        asset_type="pm_trigger_event",
        asset_id=str(normalized["event_id"]),
        payload=normalized,
        trace_id=trace_id,
        actor_role="system",
        group_key="pm",
        metadata=dict(metadata or {}),
    )
    envelope = EventFactory.build(
        trace_id=trace_id,
        event_type=EVENT_PM_TRIGGER_DETECTED,
        source_module=MODULE_NAME,
        entity_type="pm_trigger_event",
        entity_id=str(normalized["event_id"]),
        payload=normalized,
    )
    memory_assets.append_event(envelope)
    if event_bus is not None:
        try:
            event_bus.publish(envelope)
        except Exception:
            pass
    return normalized
