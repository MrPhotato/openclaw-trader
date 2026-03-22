from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class FetchedNewsItem(BaseModel):
    source: str
    title: str
    url: str
    published_at: datetime | None = None
    summary: str | None = None
    tags: list[str] = Field(default_factory=list)
    severity: str = "low"
    layer: str = "news"
