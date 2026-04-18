from __future__ import annotations

from typing import Protocol

from .models import EtfActivity, FearGreedIndex, MacroPrice


class MacroDataProvider(Protocol):
    def fetch_quote(self, yahoo_symbol: str) -> MacroPrice: ...

    def fetch_etf_activity(self, ticker: str) -> EtfActivity: ...


class SentimentProvider(Protocol):
    def fetch_btc_fear_greed(self) -> FearGreedIndex: ...
