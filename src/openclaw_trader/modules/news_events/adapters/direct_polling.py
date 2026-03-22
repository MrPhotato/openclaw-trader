from __future__ import annotations

from datetime import datetime, timezone

from ....config.loader import load_system_settings
from ....config.models import NewsConfig, NewsSource
from ...news_events.models import NewsDigestEvent
from .source_fetchers import fetch_feed, fetch_fed_fomc_calendar, fetch_okx_announcements


class DirectPollingNewsProvider:
    def __init__(
        self,
        *,
        config: NewsConfig | None = None,
        feed_fetcher=fetch_feed,
        okx_fetcher=fetch_okx_announcements,
        fomc_fetcher=fetch_fed_fomc_calendar,
    ) -> None:
        self.config = config or load_system_settings().news
        self.feed_fetcher = feed_fetcher
        self.okx_fetcher = okx_fetcher
        self.fomc_fetcher = fomc_fetcher
        self._latest: list[NewsDigestEvent] = []

    def sync(self) -> list[NewsDigestEvent]:
        items = self._poll_news()
        self._latest = [
            NewsDigestEvent(
                news_id=f"news-{index}",
                source=item.source,
                title=item.title,
                url=item.url,
                summary=item.summary,
                severity=item.severity,
                published_at=item.published_at,
                tags=item.tags,
            )
            for index, item in enumerate(items, start=1)
        ]
        return list(self._latest)

    def latest(self) -> list[NewsDigestEvent]:
        return list(self._latest)

    def _poll_news(self):
        items = []
        seen: set[tuple[str, str]] = set()
        for source in self.config.sources:
            if not source.enabled:
                continue
            try:
                fetched = self._fetch_source(source)
            except Exception:
                continue
            for item in fetched:
                key = (item.url.strip().lower(), item.title.strip().lower())
                if key in seen:
                    continue
                seen.add(key)
                items.append(item)
        items.sort(
            key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return items

    def _fetch_source(self, source: NewsSource):
        if source.type in {"rss", "atom", "feed"}:
            return self.feed_fetcher(source)
        if source.type == "html-okx-announcements":
            return self.okx_fetcher(source)
        if source.type == "html-fed-fomc-calendar":
            return self.fomc_fetcher(source)
        return []
