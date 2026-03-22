from __future__ import annotations

import unittest
from datetime import UTC, datetime

from openclaw_trader.config.models import NewsConfig, NewsSource
from openclaw_trader.modules.news_events.adapters import DirectPollingNewsProvider
from openclaw_trader.modules.news_events.adapters.source_fetchers import FetchedNewsItem
from openclaw_trader.modules.news_events.service import NewsEventService

from .helpers_v2 import FakeNewsProvider


class NewsEventServiceTests(unittest.TestCase):
    def test_sync_event_contains_digest(self) -> None:
        service = NewsEventService(FakeNewsProvider(severity="medium"))
        items = service.sync()
        event = service.build_sync_event(trace_id="trace-1", events=items)
        self.assertEqual(len(items), 1)
        self.assertEqual(event.payload["count"], 1)

    def test_direct_polling_provider_keeps_latest_after_sync(self) -> None:
        provider = DirectPollingNewsProvider(
            config=NewsConfig(
                sources=[
                    NewsSource(
                        id="rss-1",
                        type="rss",
                        url="https://example.com/feed.xml",
                        max_items=5,
                    )
                ]
            ),
            feed_fetcher=lambda source: [
                FetchedNewsItem(
                    source=source.id,
                    title="BTC ETF headline",
                    url="https://example.com/a",
                    published_at=datetime.now(UTC),
                )
            ],
        )
        items = provider.sync()
        self.assertEqual(len(items), 1)
        self.assertEqual(provider.latest()[0].title, "BTC ETF headline")


if __name__ == "__main__":
    unittest.main()
