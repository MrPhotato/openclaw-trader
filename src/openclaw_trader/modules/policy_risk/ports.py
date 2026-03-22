from __future__ import annotations

from typing import Protocol

from ..trade_gateway.market_data.models import DataIngestBundle
from ..news_events.models import NewsDigestEvent
from ..quant_intelligence.models import CoinForecast
from .models import GuardDecision


class PolicyEngine(Protocol):
    def evaluate(
        self,
        *,
        market: DataIngestBundle,
        forecasts: dict[str, CoinForecast],
        news_events: list[NewsDigestEvent],
    ) -> dict[str, GuardDecision]: ...
