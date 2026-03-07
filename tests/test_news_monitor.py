from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from openclaw_trader.config import NewsConfig, NewsSource
from openclaw_trader.news.monitor import sync_news
from openclaw_trader.state import StateStore


RSS_XML = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Crypto Feed</title>
    <item>
      <title>Bitcoin ETF headline</title>
      <link>https://example.com/etf</link>
      <description>ETF and bitcoin news.</description>
      <pubDate>Mon, 02 Mar 2026 09:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


class _Response:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        return None


class NewsMonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "state.db"
        self.store = StateStore(self.db_path)
        self.news_json = Path(self.tmpdir.name) / "news-brief.json"
        self.news_md = Path(self.tmpdir.name) / "news-brief.md"
        self.config = NewsConfig(
            poll_seconds=300,
            sources=[
                NewsSource(
                    id="coindesk-rss",
                    type="rss",
                    url="https://example.com/rss.xml",
                    layer="structured-news",
                    tags=["btc"],
                )
            ],
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_sync_news_dedupes_and_writes_brief(self) -> None:
        now = datetime(2026, 3, 2, 10, 0, tzinfo=UTC)
        with patch("openclaw_trader.news.rss.httpx.Client.get", return_value=_Response(RSS_XML)), \
             patch("openclaw_trader.news.monitor.NEWS_BRIEF_JSON", self.news_json), \
             patch("openclaw_trader.news.monitor.NEWS_BRIEF_MD", self.news_md):
            first = sync_news(self.config, self.store, now=now)
            second = sync_news(self.config, self.store, now=now)
        self.assertTrue(first.polled)
        self.assertEqual(len(first.new_items), 1)
        self.assertFalse(second.polled)
        self.assertEqual(len(self.store.list_recent_news(now=now)), 1)
        payload = json.loads(self.news_json.read_text())
        self.assertEqual(payload["recent_items"][0]["title"], "Bitcoin ETF headline")
        self.assertIn("structured-news:1", payload["summary"])

    def test_sync_news_does_not_advance_sync_when_all_sources_fail(self) -> None:
        now = datetime(2026, 3, 2, 10, 0, tzinfo=UTC)
        with patch("openclaw_trader.news.monitor.poll_news_with_status") as poll_news, \
             patch("openclaw_trader.news.monitor.NEWS_BRIEF_JSON", self.news_json), \
             patch("openclaw_trader.news.monitor.NEWS_BRIEF_MD", self.news_md):
            from openclaw_trader.news.service import NewsPollResult

            poll_news.return_value = NewsPollResult(
                items=[],
                enabled_sources=1,
                successful_sources=0,
                failed_sources=["coindesk-rss"],
            )
            result = sync_news(self.config, self.store, now=now)
        self.assertTrue(result.polled)
        self.assertEqual(result.poll_error, "all_enabled_sources_failed:coindesk-rss")
        self.assertIsNone(self.store.get_value("news:last_sync_at"))
        self.assertEqual(self.store.get_value("news:last_sync_error"), "all_enabled_sources_failed:coindesk-rss")
        payload = json.loads(self.news_json.read_text())
        self.assertEqual(payload["poll_error"], "all_enabled_sources_failed:coindesk-rss")


if __name__ == "__main__":
    unittest.main()
