from __future__ import annotations

from ...shared.protocols import EventFactory
from .events import EVENT_NEWS_BATCH_READY, MODULE_NAME
from .models import NewsDigestEvent
from .ports import NewsProvider


class NewsEventService:
    def __init__(self, provider: NewsProvider) -> None:
        self.provider = provider

    def get_latest_news_batch(self, *, force_sync: bool = False) -> list[NewsDigestEvent]:
        return self.sync() if force_sync else self.latest()

    def get_recent_high_impact_events(self, *, force_sync: bool = False) -> list[NewsDigestEvent]:
        batch = self.get_latest_news_batch(force_sync=force_sync)
        return [item for item in batch if str(item.severity).lower() == "high"]

    def sync(self) -> list[NewsDigestEvent]:
        return self.provider.sync()

    def latest(self) -> list[NewsDigestEvent]:
        return self.provider.latest()

    def build_sync_event(self, *, trace_id: str, events: list[NewsDigestEvent]):
        return EventFactory.build(
            trace_id=trace_id,
            event_type=EVENT_NEWS_BATCH_READY,
            source_module=MODULE_NAME,
            entity_type="news_batch",
            payload={"count": len(events), "events": [item.model_dump(mode="json") for item in events]},
        )
