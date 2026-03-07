from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from ..config import NewsSource
from ..models import NewsItem


def _clean_text(value: str | None) -> str:
    return " ".join((value or "").split())


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _parse_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        pass
    try:
        normalized = raw.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return None


def _first_text(parent: ET.Element, *names: str) -> str | None:
    for child in list(parent):
        if _local_name(child.tag) in names:
            text = _clean_text(child.text)
            if text:
                return text
    return None


def _first_link(parent: ET.Element, default: str) -> str:
    for child in list(parent):
        if _local_name(child.tag) != "link":
            continue
        href = (child.attrib.get("href") or "").strip()
        if href:
            return href
        text = _clean_text(child.text)
        if text:
            return text
    return default


def _infer_severity(source: NewsSource, title: str, summary: str) -> str:
    haystack = f"{title} {summary}".lower()
    layer = source.layer.lower()
    tags = {tag.lower() for tag in source.tags}

    if layer == "exchange-status":
        if any(token in haystack for token in ["major outage", "system outage", "critical", "service outage"]):
            return "high"
        if any(token in haystack for token in ["degraded service", "investigating", "identified", "partial outage", "maintenance"]):
            return "medium"
        return "low"

    if layer == "regulation" or "regulation" in tags:
        if any(token in haystack for token in ["bitcoin", "btc", "crypto", "digital asset", "etf", "stablecoin", "exchange"]):
            return "medium"
        return "low"

    if layer == "macro" or "macro" in tags:
        if any(token in haystack for token in ["fomc", "monetary policy", "interest rate", "rate decision", "inflation", "powell", "federal reserve"]):
            return "medium"
        return "low"

    if layer == "official-x" or "official-x" in tags:
        if any(token in haystack for token in ["listing", "launch", "maintenance", "incident", "outage", "etf", "approval", "delist", "perp", "futures"]):
            return "medium"
        return "low"

    if layer == "exchange-announcement":
        if any(token in haystack for token in ["listing", "launch", "maintenance", "delist", "incident", "futures", "perpetual"]):
            return "medium"
        return "low"

    if layer == "event-calendar":
        if any(token in haystack for token in ["fomc", "cpi", "powell", "rate"]):
            return "medium"
        return "low"

    return "low"


def _parse_rss_items(root: ET.Element, source: NewsSource) -> list[NewsItem]:
    items: list[NewsItem] = []
    for item in root.findall(".//item")[: source.max_items]:
        title = _clean_text(item.findtext("title"))
        if not title:
            continue
        summary = _clean_text(item.findtext("description"))[:500] or None
        items.append(
            NewsItem(
                source=source.id,
                title=title,
                url=_clean_text(item.findtext("link") or source.url),
                published_at=_parse_datetime(item.findtext("pubDate") or item.findtext("date")),
                summary=summary,
                tags=source.tags,
                severity=_infer_severity(source, title, summary or ""),
                layer=source.layer,
            )
        )
    return items


def _parse_atom_entries(root: ET.Element, source: NewsSource) -> list[NewsItem]:
    items: list[NewsItem] = []
    entries = [node for node in root.iter() if _local_name(node.tag) == "entry"]
    for entry in entries[: source.max_items]:
        title = _clean_text(_first_text(entry, "title"))
        if not title:
            continue
        summary = _clean_text(_first_text(entry, "summary", "content"))[:500] or None
        items.append(
            NewsItem(
                source=source.id,
                title=title,
                url=_first_link(entry, source.url),
                published_at=_parse_datetime(_first_text(entry, "updated", "published")),
                summary=summary,
                tags=source.tags,
                severity=_infer_severity(source, title, summary or ""),
                layer=source.layer,
            )
        )
    return items


def fetch_feed(source: NewsSource, timeout: float = 15.0) -> list[NewsItem]:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(source.url)
        resp.raise_for_status()
    root = ET.fromstring(resp.text)

    if _local_name(root.tag) == "feed" or any(_local_name(node.tag) == "entry" for node in root.iter()):
        return _parse_atom_entries(root, source)
    return _parse_rss_items(root, source)
