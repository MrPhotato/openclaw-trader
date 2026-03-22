from __future__ import annotations

from datetime import UTC, datetime
from pydantic import BaseModel, Field


class NewsDigestEvent(BaseModel):
    news_id: str
    source: str
    title: str
    url: str
    summary: str | None = None
    severity: str = "low"
    published_at: datetime | None = None
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tags: list[str] = Field(default_factory=list)
