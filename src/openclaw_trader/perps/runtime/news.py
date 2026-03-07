from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ...models import NewsItem


def _exchange_keywords(exchange: object) -> tuple[str, ...]:
    normalized = str(exchange).strip().lower()
    return {
        "hyperliquid": ("hyperliquid",),
        "coinbase_intx": ("coinbase", "intx", "perpetual"),
        "coinbase-intx": ("coinbase", "intx", "perpetual"),
        "coinbase": ("coinbase", "intx", "perpetual"),
    }.get(normalized, (normalized,))


def is_fresh_news(item: NewsItem, max_age_minutes: int) -> bool:
    if item.published_at is None:
        return False
    published_at = item.published_at if item.published_at.tzinfo else item.published_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if published_at > now:
        return published_at - now <= timedelta(hours=24)
    return now - published_at <= timedelta(minutes=max_age_minutes)


def is_market_relevant_news(item: NewsItem, *, exchange: object) -> bool:
    layer = item.layer.lower()
    if layer in {"macro", "regulation", "event-calendar", "structured-news"}:
        return True
    if layer in {"exchange-status", "exchange-announcement", "official-x"}:
        haystack = f"{item.source.lower()} {item.title.lower()} {item.url.lower()}"
        return any(keyword in haystack for keyword in _exchange_keywords(exchange))
    return False


def is_relevant_news(item: NewsItem, coin: str, *, exchange: object) -> bool:
    if not is_market_relevant_news(item, exchange=exchange):
        return False
    haystack = f"{item.title} {item.summary or ''}".lower()
    exchange_tokens = set(_exchange_keywords(exchange))
    symbol_tokens = {
        "BTC": {"btc", "bitcoin", "crypto", "etf", "fomc", "powell", "cpi", "fed", "rates"},
        "ETH": {"eth", "ethereum", "crypto", "etf", "fomc", "powell", "cpi", "fed", "rates"},
        "SOL": {"sol", "solana", "crypto", "etf", "fomc", "powell", "cpi", "fed", "rates"},
    }
    tokens = symbol_tokens.get(coin.upper(), {coin.lower()}) | exchange_tokens
    if any(token in haystack for token in tokens):
        return True
    if item.layer in {"macro", "regulation", "exchange-status", "exchange-announcement", "official-x", "event-calendar"} and item.severity in {"medium", "high"}:
        return True
    return False
