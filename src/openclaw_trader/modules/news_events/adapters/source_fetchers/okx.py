from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urljoin

import httpx

from .....config.models import NewsSource
from .common import clean_text
from .models import FetchedNewsItem


def fetch_okx_announcements(source: NewsSource, timeout: float = 15.0) -> list[FetchedNewsItem]:
    with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
        response = client.get(source.url)
        response.raise_for_status()
        body = response.text

    pattern = re.compile(
        r'<a href="(?P<href>/en-us/help/[^"]+)"[^>]*>.*?<div[^>]*>(?P<title>[^<]+)</div>.*?<span[^>]*>Published on (?P<date>[^<]+)</span>',
        re.S,
    )
    items: list[FetchedNewsItem] = []
    for match in pattern.finditer(body):
        title = clean_text(match.group("title"))
        if not title:
            continue
        published_at = datetime.strptime(match.group("date"), "%b %d, %Y").replace(tzinfo=UTC)
        severity = "medium" if any(token in title.lower() for token in ["list", "launch", "futures", "maintenance", "delist"]) else "low"
        items.append(
            FetchedNewsItem(
                source=source.id,
                title=title,
                url=urljoin("https://www.okx.com", match.group("href")),
                published_at=published_at,
                summary=None,
                tags=source.tags,
                severity=severity,
                layer=source.layer,
            )
        )
        if len(items) >= source.max_items:
            break
    return items
