from __future__ import annotations

import re
from datetime import UTC, datetime

import httpx

from .....config.models import NewsSource
from .common import month_name_to_number
from .models import FetchedNewsItem


def fetch_fed_fomc_calendar(source: NewsSource, timeout: float = 15.0) -> list[FetchedNewsItem]:
    with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
        response = client.get(source.url)
        response.raise_for_status()
        body = response.text

    year_match = re.search(r"(\d{4}) FOMC Meetings", body)
    if not year_match:
        return []
    year = int(year_match.group(1))
    start_idx = year_match.start()
    next_idx = body.find(f"{year + 1} FOMC Meetings", start_idx + 1)
    section = body[start_idx : next_idx if next_idx != -1 else len(body)]
    pattern = re.compile(
        r'fomc-meeting__month[^>]*><strong>(?P<month>[A-Za-z]+)</strong>.*?fomc-meeting__date[^>]*>(?P<date>[^<]+)</div>',
        re.S,
    )
    items: list[FetchedNewsItem] = []
    now = datetime.now(UTC)
    for match in pattern.finditer(section):
        month = month_name_to_number(match.group("month"))
        raw_date = re.sub(r"[^0-9-]", "", match.group("date"))
        if not raw_date:
            continue
        start_day = int(raw_date.split("-", 1)[0])
        event_at = datetime(year, month, start_day, tzinfo=UTC)
        if event_at < now.replace(hour=0, minute=0, second=0, microsecond=0):
            continue
        title = f"FOMC {match.group('month')} {match.group('date')} meeting"
        severity = "high" if (event_at - now).days <= 2 else "medium"
        items.append(
            FetchedNewsItem(
                source=source.id,
                title=title,
                url=source.url,
                published_at=event_at,
                summary="Upcoming FOMC meeting window.",
                tags=source.tags,
                severity=severity,
                layer=source.layer,
            )
        )
        if len(items) >= source.max_items:
            break
    return items
