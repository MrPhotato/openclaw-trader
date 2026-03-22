from __future__ import annotations

from ....shared.protocols import EventFactory
from ....shared.utils import new_id
from .events import EVENT_ACCOUNT_COLLECTED, EVENT_MARKET_COLLECTED, MODULE_NAME
from .models import DataIngestBundle, ExecutionHistorySnapshot, MarketContextNormalized, ProductMetadataSnapshot
from .ports import MarketDataProvider


class DataIngestService:
    def __init__(self, provider: MarketDataProvider) -> None:
        self.provider = provider

    def get_market_overview(self, *, trace_id: str | None = None, coins: list[str] | None = None) -> DataIngestBundle:
        return self.collect(trace_id=trace_id, coins=coins)

    def get_light_market_context(self, *, trace_id: str | None = None, coins: list[str] | None = None) -> DataIngestBundle:
        return self.collect(trace_id=trace_id, coins=coins)

    def get_execution_context_facts(self, *, trace_id: str | None = None, coins: list[str] | None = None) -> DataIngestBundle:
        return self.collect(trace_id=trace_id, coins=coins)

    def collect(self, *, trace_id: str | None = None, coins: list[str] | None = None) -> DataIngestBundle:
        trace = trace_id or new_id("trace")
        target_coins = coins or ["BTC", "ETH", "SOL"]
        market = self.provider.collect_market(target_coins)
        accounts = self.provider.collect_accounts(target_coins)
        portfolio = self.provider.collect_portfolio()
        market_context = self.provider.collect_market_context(target_coins)
        execution_history = self.provider.collect_execution_history(target_coins)
        product_metadata = self.provider.collect_product_metadata(target_coins)
        return DataIngestBundle(
            trace_id=trace,
            market=market,
            accounts=accounts,
            portfolio=portfolio,
            market_context=market_context,
            execution_history=execution_history,
            product_metadata=product_metadata,
        )

    def collect_market_context(
        self,
        *,
        coins: list[str] | None = None,
    ) -> dict[str, MarketContextNormalized]:
        target_coins = coins or ["BTC", "ETH", "SOL"]
        return self.provider.collect_market_context(target_coins)

    def collect_execution_history(
        self,
        *,
        coins: list[str] | None = None,
    ) -> dict[str, ExecutionHistorySnapshot]:
        target_coins = coins or ["BTC", "ETH", "SOL"]
        return self.provider.collect_execution_history(target_coins)

    def collect_product_metadata(
        self,
        *,
        coins: list[str] | None = None,
    ) -> dict[str, ProductMetadataSnapshot]:
        target_coins = coins or ["BTC", "ETH", "SOL"]
        return self.provider.collect_product_metadata(target_coins)

    def build_market_events(self, bundle: DataIngestBundle):
        events = []
        for coin, snapshot in bundle.market.items():
            events.append(
                EventFactory.build(
                    trace_id=bundle.trace_id,
                    event_type=EVENT_MARKET_COLLECTED,
                    source_module=MODULE_NAME,
                    entity_type="market_snapshot",
                    entity_id=snapshot.snapshot_id,
                    payload={"coin": coin, "snapshot": snapshot.model_dump(mode="json")},
                )
            )
        for coin, account in bundle.accounts.items():
            events.append(
                EventFactory.build(
                    trace_id=bundle.trace_id,
                    event_type=EVENT_ACCOUNT_COLLECTED,
                    source_module=MODULE_NAME,
                    entity_type="account_snapshot",
                    entity_id=coin,
                    payload={"coin": coin, "account": account.model_dump(mode="json")},
                )
            )
        return events
