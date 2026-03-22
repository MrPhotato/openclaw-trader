from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from .....config.models import NewsSource
from .common import clean_text, first_link, first_text, local_name, parse_datetime
from .models import FetchedNewsItem
from .severity import infer_severity


def _parse_rss_items(root: ET.Element, source: NewsSource) -> list[FetchedNewsItem]:
    items: list[FetchedNewsItem] = []
    for item in root.findall(".//item")[: source.max_items]:
        title = clean_text(item.findtext("title"))
        if not title:
            continue
        summary = clean_text(item.findtext("description"))[:500] or None
        items.append(
            FetchedNewsItem(
                source=source.id,
                title=title,
                url=clean_text(item.findtext("link") or source.url),
                published_at=parse_datetime(item.findtext("pubDate") or item.findtext("date")),
                summary=summary,
                tags=source.tags,
                severity=infer_severity(source, title, summary or ""),
                layer=source.layer,
            )
        )
    return items


def _parse_atom_entries(root: ET.Element, source: NewsSource) -> list[FetchedNewsItem]:
    items: list[FetchedNewsItem] = []
    entries = [node for node in root.iter() if local_name(node.tag) == "entry"]
    for entry in entries[: source.max_items]:
        title = clean_text(first_text(entry, "title"))
        if not title:
            continue
        summary = clean_text(first_text(entry, "summary", "content"))[:500] or None
        items.append(
            FetchedNewsItem(
                source=source.id,
                title=title,
                url=first_link(entry, source.url),
                published_at=parse_datetime(first_text(entry, "updated", "published")),
                summary=summary,
                tags=source.tags,
                severity=infer_severity(source, title, summary or ""),
                layer=source.layer,
            )
        )
    return items


def fetch_feed(source: NewsSource, timeout: float = 15.0) -> list[FetchedNewsItem]:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(source.url)
        response.raise_for_status()
    root = ET.fromstring(response.text)
    if local_name(root.tag) == "feed" or any(local_name(node.tag) == "entry" for node in root.iter()):
        return _parse_atom_entries(root, source)
    return _parse_rss_items(root, source)
