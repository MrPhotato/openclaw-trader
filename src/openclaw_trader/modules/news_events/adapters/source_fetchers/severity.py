from __future__ import annotations

from .....config.models import NewsSource


def infer_severity(source: NewsSource, title: str, summary: str) -> str:
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

    if layer == "event-calendar":
        if any(token in haystack for token in ["fomc", "cpi", "powell", "rate"]):
            return "medium"
        return "low"

    if any(token in haystack for token in ["listing", "launch", "maintenance", "delist", "incident", "futures", "perpetual"]):
        return "medium"
    return "low"
