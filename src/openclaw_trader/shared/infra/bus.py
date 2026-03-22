from __future__ import annotations

import json
from typing import Protocol

try:  # pragma: no cover - optional import for local test environments
    import pika
except ModuleNotFoundError:  # pragma: no cover - deferred until RabbitMQ is used
    pika = None

from ...config.loader import load_system_settings
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


class RabbitMQEventBus:
    def __init__(self, url: str | None = None, exchange_name: str | None = None) -> None:
        if pika is None:
            raise RuntimeError("pika is required to use RabbitMQEventBus")
        settings = load_system_settings()
        self.url = url or settings.bus.rabbitmq_url
        self.exchange_name = exchange_name or settings.bus.exchange_name
        self._connection: pika.BlockingConnection | None = None
        self._channel: pika.adapters.blocking_connection.BlockingChannel | None = None

    def _ensure_channel(self):
        if self._channel is not None and self._channel.is_open:
            return self._channel
        parameters = pika.URLParameters(self.url)
        self._connection = pika.BlockingConnection(parameters)
        self._channel = self._connection.channel()
        self._channel.exchange_declare(exchange=self.exchange_name, exchange_type="topic", durable=True)
        return self._channel

    def publish(self, envelope: EventEnvelope) -> None:
        channel = self._ensure_channel()
        routing_key = envelope.event_type
        body = envelope.model_dump_json().encode("utf-8")
        channel.basic_publish(
            exchange=self.exchange_name,
            routing_key=routing_key,
            body=body,
            properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
        )

    def close(self) -> None:
        if self._channel is not None and self._channel.is_open:
            self._channel.close()
        if self._connection is not None and self._connection.is_open:
            self._connection.close()


def decode_event_payload(raw: bytes | str) -> EventEnvelope:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return EventEnvelope.model_validate(json.loads(raw))
