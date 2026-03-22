from __future__ import annotations

from typing import Protocol

from .models import NewsDigestEvent


class NewsProvider(Protocol):
    def sync(self) -> list[NewsDigestEvent]: ...

    def latest(self) -> list[NewsDigestEvent]: ...
