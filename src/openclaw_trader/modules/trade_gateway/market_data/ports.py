from __future__ import annotations

from typing import Protocol

from .models import (
    AccountSnapshot,
    ExecutionHistorySnapshot,
    MarketContextNormalized,
    MarketSnapshotNormalized,
    PortfolioSnapshot,
    ProductMetadataSnapshot,
)


class MarketDataProvider(Protocol):
    def collect_market(self, coins: list[str]) -> dict[str, MarketSnapshotNormalized]: ...

    def collect_accounts(self, coins: list[str]) -> dict[str, AccountSnapshot]: ...

    def collect_portfolio(self) -> PortfolioSnapshot: ...

    def collect_product_metadata(self, coins: list[str]) -> dict[str, ProductMetadataSnapshot]: ...

    def collect_market_context(self, coins: list[str]) -> dict[str, MarketContextNormalized]: ...

    def collect_execution_history(self, coins: list[str]) -> dict[str, ExecutionHistorySnapshot]: ...
