from __future__ import annotations

import json
from typing import Protocol
from ..protocols.events import EventEnvelope


class EventBus(Protocol):
    def publish(self, envelope: EventEnvelope) -> None: ...

    def close(self) -> None: ...


class InMemoryEventBus:
    def __init__(self) -> None:
        self.published: list[EventEnvelope] = []

    def publish(self, envelope: EventEnvelope) -> None:
        self.published.append(envelope)

    def close(self) -> None:
        return None


def decode_event_payload(raw: bytes | str) -> EventEnvelope:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return EventEnvelope.model_validate(json.loads(raw))
