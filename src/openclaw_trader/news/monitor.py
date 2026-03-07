from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..config import REPORT_DIR, NewsConfig
from ..models import NewsItem
from ..state import StateStore
from .service import poll_news_with_status


NEWS_BRIEF_JSON = REPORT_DIR / "news-brief.json"
NEWS_BRIEF_MD = REPORT_DIR / "news-brief.md"


@dataclass
class NewsSyncResult:
    polled: bool
    new_items: list[NewsItem]
    recent_items: list[NewsItem]
    urgent_items: list[NewsItem]
    successful_sources: int = 0
    failed_sources: list[str] | None = None
    poll_error: str | None = None


def _should_poll(config: NewsConfig, state: StateStore, now: datetime) -> bool:
    raw = state.get_value("news:last_sync_at")
    if not raw:
        return True
    last_sync = datetime.fromisoformat(raw)
    if last_sync.tzinfo is None:
        last_sync = last_sync.replace(tzinfo=UTC)
    return now - last_sync >= timedelta(seconds=config.poll_seconds)


def _summary_text(items: list[NewsItem], urgent_items: list[NewsItem], poll_error: str | None = None) -> str:
    prefix = f"新闻轮询异常：{poll_error} " if poll_error else ""
    if not items:
        return prefix + "过去24小时无新的高价值新闻。"
    counts = Counter(item.layer for item in items)
    parts = []
    for layer in ("exchange-status", "exchange-announcement", "official-x", "macro", "regulation", "structured-news", "event-calendar"):
        count = counts.get(layer, 0)
        if count:
            parts.append(f"{layer}:{count}")
    summary = "过去24小时新闻风向：" + "，".join(parts) if parts else "过去24小时新闻较平静。"
    if urgent_items:
        urgent_titles = "；".join(item.title for item in urgent_items[:3])
        return f"{prefix}{summary} 重点：{urgent_titles}"
    return prefix + summary


def _write_brief(items: list[NewsItem], urgent_items: list[NewsItem], now: datetime, *, poll_error: str | None = None) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": now.astimezone(UTC).isoformat(),
        "summary": _summary_text(items, urgent_items, poll_error),
        "poll_error": poll_error,
        "urgent_items": [item.model_dump(mode="json") for item in urgent_items[:5]],
        "recent_items": [item.model_dump(mode="json") for item in items[:10]],
    }
    NEWS_BRIEF_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    lines = [
        f"生成时间：{payload['generated_at']}",
        payload["summary"],
        "",
        "重点新闻：",
    ]
    if urgent_items:
        lines.extend(f"- {item.title}" for item in urgent_items[:5])
    else:
        lines.append("- 无")
    NEWS_BRIEF_MD.write_text("\n".join(lines))


def sync_news(config: NewsConfig, state: StateStore, now: datetime | None = None) -> NewsSyncResult:
    now = now or datetime.now(UTC)
    polled = False
    new_items: list[NewsItem] = []
    successful_sources = 0
    failed_sources: list[str] = []
    poll_error: str | None = None
    if _should_poll(config, state, now):
        polled = True
        poll_result = poll_news_with_status(config)
        successful_sources = poll_result.successful_sources
        failed_sources = poll_result.failed_sources
        for item in poll_result.items:
            if state.record_news_if_new(item, now=now):
                new_items.append(item)
        if poll_result.enabled_sources > 0 and poll_result.successful_sources == 0 and poll_result.failed_sources:
            poll_error = "all_enabled_sources_failed:" + ",".join(poll_result.failed_sources)
            state.set_value("news:last_sync_error", poll_error, now=now)
            state.set_value("news:last_sync_error_at", now.astimezone(UTC).isoformat(), now=now)
        else:
            if poll_result.failed_sources:
                poll_error = "partial_source_failures:" + ",".join(poll_result.failed_sources)
            state.set_value("news:last_sync_at", now.astimezone(UTC).isoformat(), now=now)
            state.set_value("news:last_sync_error", poll_error or "", now=now)
    recent_items = state.list_recent_news(max_age_minutes=24 * 60, limit=50, now=now)
    urgent_items = [item for item in recent_items if item.severity in {"medium", "high"}][:5]
    _write_brief(recent_items, urgent_items, now, poll_error=poll_error)
    return NewsSyncResult(
        polled=polled,
        new_items=new_items,
        recent_items=recent_items,
        urgent_items=urgent_items,
        successful_sources=successful_sources,
        failed_sources=failed_sources,
        poll_error=poll_error,
    )
