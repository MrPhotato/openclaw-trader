from __future__ import annotations

import unittest
from datetime import timezone
from unittest.mock import patch

from openclaw_trader.config import NewsConfig, NewsSource
from openclaw_trader.models import NewsItem
from openclaw_trader.news.html import fetch_fed_fomc_calendar, fetch_okx_announcements
from openclaw_trader.news.rss import fetch_feed
from openclaw_trader.news.service import poll_news


class _Response:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


RSS_XML = """<?xml version='1.0' encoding='UTF-8'?>
<rss version='2.0'>
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Bitcoin ETF approval headline</title>
      <link>https://example.com/rss-1</link>
      <pubDate>Mon, 03 Mar 2026 01:02:03 GMT</pubDate>
      <description>ETF and bitcoin news.</description>
    </item>
  </channel>
</rss>
"""

ATOM_XML = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns='http://www.w3.org/2005/Atom'>
  <title>Status</title>
  <entry>
    <title>Investigating: degraded service</title>
    <updated>2026-03-03T02:02:03Z</updated>
    <summary>Partial outage on exchange.</summary>
    <link href='https://status.example.com/incidents/1'/>
  </entry>
</feed>
"""

OKX_HTML = """
<li class="index_articleItem__d-8iK">
  <a href="/en-us/help/okx-to-list-abc-for-spot-trading">
    <div class="index_title__iTmos index_articleTitle__ys7G7">OKX to list ABC for spot trading</div>
    <div class="index_dividerRow__FHkzs index_detailsRow__8Gmjm"><span class="">Published on Feb 12, 2026</span></div>
  </a>
</li>
"""

FOMC_HTML = """
<h4><a>2026 FOMC Meetings</a></h4>
<div class="row fomc-meeting">
  <div class="fomc-meeting__month"><strong>March</strong></div>
  <div class="fomc-meeting__date">17-18*</div>
</div>
<div class="row fomc-meeting">
  <div class="fomc-meeting__month"><strong>May</strong></div>
  <div class="fomc-meeting__date">6-7</div>
</div>
"""


class FeedParsingTests(unittest.TestCase):
    def _patch_client(self, payload: str):
        return patch('openclaw_trader.news.rss.httpx.Client.get', return_value=_Response(payload))

    def _patch_html_client(self, payload: str):
        return patch('openclaw_trader.news.html.httpx.Client.get', return_value=_Response(payload))

    def test_fetch_rss_feed(self) -> None:
        source = NewsSource(
            id='coindesk-rss',
            type='rss',
            url='https://example.com/feed.xml',
            tags=['market-news', 'btc'],
            layer='structured-news',
        )
        with self._patch_client(RSS_XML):
            items = fetch_feed(source)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, 'Bitcoin ETF approval headline')
        self.assertEqual(items[0].layer, 'structured-news')
        self.assertEqual(items[0].published_at.tzinfo, timezone.utc)

    def test_fetch_atom_feed(self) -> None:
        source = NewsSource(
            id='coinbase-status',
            type='atom',
            url='https://status.example.com/history.atom',
            tags=['exchange-status', 'risk'],
            layer='exchange-status',
        )
        with self._patch_client(ATOM_XML):
            items = fetch_feed(source)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].url, 'https://status.example.com/incidents/1')
        self.assertEqual(items[0].severity, 'medium')

    def test_poll_news_dedupes_and_sorts(self) -> None:
        source_a = NewsSource(id='coindesk-rss', type='rss', url='https://example.com/a.xml', layer='structured-news')
        source_b = NewsSource(id='coinbase-status', type='atom', url='https://example.com/b.atom', layer='exchange-status')
        config = NewsConfig(sources=[source_a, source_b])

        with patch('openclaw_trader.news.rss.httpx.Client.get', side_effect=[_Response(RSS_XML), _Response(ATOM_XML)]):
            items = poll_news(config)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].source, 'coinbase-status')
        self.assertEqual(items[1].source, 'coindesk-rss')

    def test_fetch_okx_announcements_html(self) -> None:
        source = NewsSource(
            id='okx-announcements',
            type='html-okx-announcements',
            url='https://www.okx.com/en-us/help/section/announcements-latest-announcements',
            layer='exchange-announcement',
        )
        with self._patch_html_client(OKX_HTML):
            items = fetch_okx_announcements(source)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, 'OKX to list ABC for spot trading')
        self.assertEqual(items[0].severity, 'medium')

    def test_fetch_fed_fomc_calendar_html(self) -> None:
        source = NewsSource(
            id='fed-fomc-calendar',
            type='html-fed-fomc-calendar',
            url='https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm',
            layer='event-calendar',
        )
        with self._patch_html_client(FOMC_HTML):
            items = fetch_fed_fomc_calendar(source)
        self.assertGreaterEqual(len(items), 1)
        self.assertEqual(items[0].layer, 'event-calendar')

    def test_poll_news_skips_failing_source(self) -> None:
        config = NewsConfig(
            sources=[
                NewsSource(id='slow-feed', type='rss', url='https://example.com/slow.xml', layer='structured-news'),
                NewsSource(
                    id='okx-announcements',
                    type='html-okx-announcements',
                    url='https://www.okx.com/en-us/help/section/announcements-latest-announcements',
                    layer='exchange-announcement',
                ),
            ]
        )
        with patch('openclaw_trader.news.service.fetch_feed', side_effect=TimeoutError('timeout')), patch(
            'openclaw_trader.news.service.fetch_okx_announcements',
            return_value=[
                NewsItem(
                    source='okx-announcements',
                    title='OKX to list ABC for spot trading',
                    url='https://www.okx.com/en-us/help/okx-to-list-abc-for-spot-trading',
                    layer='exchange-announcement',
                    severity='medium',
                )
            ],
        ):
            items = poll_news(config)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source, 'okx-announcements')


if __name__ == '__main__':
    unittest.main()
