from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from ..utils.ids import new_id


class EventEnvelope(BaseModel):
    event_id: str
    trace_id: str
    event_type: str
    source_module: str
    entity_type: str
    schema_version: str = "1.0"
    entity_id: str | None = None
    workflow_id: str | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventFactory:
    @staticmethod
    def build(
        *,
        trace_id: str,
        event_type: str,
        source_module: str,
        entity_type: str,
        payload: dict[str, Any] | None = None,
        entity_id: str | None = None,
        workflow_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EventEnvelope:
        return EventEnvelope(
            event_id=new_id("evt"),
            trace_id=trace_id,
            event_type=event_type,
            source_module=source_module,
            entity_type=entity_type,
            entity_id=entity_id,
            workflow_id=workflow_id,
            payload=payload or {},
            metadata=metadata or {},
        )
