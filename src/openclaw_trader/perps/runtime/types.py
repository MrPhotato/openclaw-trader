from __future__ import annotations

from dataclasses import dataclass

from ...models import AutopilotDecision, NewsItem


@dataclass
class PerpSystemState:
    decisions: list[AutopilotDecision]
    primary: AutopilotDecision
    latest_news: list[NewsItem]
