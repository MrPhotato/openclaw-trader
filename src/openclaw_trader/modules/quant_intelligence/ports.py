from __future__ import annotations

from typing import Protocol

from ..trade_gateway.market_data.models import DataIngestBundle
from .models import CoinForecast


class QuantProvider(Protocol):
    def predict_market(self, market: DataIngestBundle) -> dict[str, CoinForecast]: ...

    def retrain(self, coins: list[str] | None = None) -> dict[str, dict]: ...
