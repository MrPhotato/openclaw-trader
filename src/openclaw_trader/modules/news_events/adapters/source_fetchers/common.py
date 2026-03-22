from __future__ import annotations

import html as html_lib
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def clean_text(value: str | None) -> str:
    return " ".join(html_lib.unescape(value or "").split())


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def parse_datetime(raw: str | None) -> datetime | None:
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


def first_text(parent: ET.Element, *names: str) -> str | None:
    for child in list(parent):
        if local_name(child.tag) in names:
            text = clean_text(child.text)
            if text:
                return text
    return None


def first_link(parent: ET.Element, default: str) -> str:
    for child in list(parent):
        if local_name(child.tag) != "link":
            continue
        href = (child.attrib.get("href") or "").strip()
        if href:
            return href
        text = clean_text(child.text)
        if text:
            return text
    return default


def month_name_to_number(name: str) -> int:
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
