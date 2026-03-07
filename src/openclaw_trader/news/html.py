from __future__ import annotations

import html as html_lib
import re
from datetime import UTC, datetime
from urllib.parse import urljoin

import httpx

from ..config import NewsSource
from ..models import NewsItem


def _clean_text(value: str | None) -> str:
    return " ".join(html_lib.unescape(value or "").split())


def _month_name_to_number(name: str) -> int:
    mapping = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }
    return mapping[name.lower()]


def fetch_okx_announcements(source: NewsSource, timeout: float = 15.0) -> list[NewsItem]:
    with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
        resp = client.get(source.url)
        resp.raise_for_status()
        body = resp.text

    pattern = re.compile(
        r'<a href="(?P<href>/en-us/help/[^"]+)"[^>]*>.*?<div[^>]*>(?P<title>[^<]+)</div>.*?<span[^>]*>Published on (?P<date>[^<]+)</span>',
        re.S,
    )
    items: list[NewsItem] = []
    for match in pattern.finditer(body):
        title = _clean_text(match.group("title"))
        if not title:
            continue
        published_at = datetime.strptime(match.group("date"), "%b %d, %Y").replace(tzinfo=UTC)
        severity = "medium" if any(token in title.lower() for token in ["list", "launch", "futures", "maintenance", "delist"]) else "low"
        items.append(
            NewsItem(
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


def fetch_fed_fomc_calendar(source: NewsSource, timeout: float = 15.0) -> list[NewsItem]:
    with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
        resp = client.get(source.url)
        resp.raise_for_status()
        body = resp.text

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
    items: list[NewsItem] = []
    now = datetime.now(UTC)
    for match in pattern.finditer(section):
        month = _month_name_to_number(match.group("month"))
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
            NewsItem(
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
