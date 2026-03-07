from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .html import fetch_fed_fomc_calendar, fetch_okx_announcements
from .rss import fetch_feed
from ..config import NewsConfig
from ..models import NewsItem


def _dedupe_key(item: NewsItem) -> tuple[str, str]:
    return (item.url.strip().lower(), item.title.strip().lower())


@dataclass
class NewsPollResult:
    items: list[NewsItem]
    enabled_sources: int
    successful_sources: int
    failed_sources: list[str]


def poll_news_with_status(config: NewsConfig) -> NewsPollResult:
    items: list[NewsItem] = []
    seen: set[tuple[str, str]] = set()
    enabled_sources = 0
    successful_sources = 0
    failed_sources: list[str] = []
    for source in config.sources:
        if not source.enabled:
            continue
        enabled_sources += 1
        try:
            if source.type in {"rss", "atom", "feed"}:
                fetched = fetch_feed(source)
            elif source.type == "html-okx-announcements":
                fetched = fetch_okx_announcements(source)
            elif source.type == "html-fed-fomc-calendar":
                fetched = fetch_fed_fomc_calendar(source)
            else:
                fetched = []
        except Exception:
            failed_sources.append(source.id)
            continue
        successful_sources += 1
        for item in fetched:
            key = _dedupe_key(item)
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    items.sort(
        key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return NewsPollResult(
        items=items,
        enabled_sources=enabled_sources,
        successful_sources=successful_sources,
        failed_sources=failed_sources,
    )


def poll_news(config: NewsConfig) -> list[NewsItem]:
    return poll_news_with_status(config).items
