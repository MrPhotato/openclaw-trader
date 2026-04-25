from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

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
        """Fan out the six independent provider calls in parallel.

        Each provider call below is dominated by Coinbase HTTP wall time and
        none consumes another's output. Running them serially meant
        `bridge_refresh` paid the SUM of latencies on every tick — measured
        14-23s in production on 2026-04-25, dragging the bridge cycle out to
        ~120s. Submitting them all to a small ThreadPoolExecutor cuts wall
        time to ~max(latency). Stays in stdlib (concurrent.futures), no new
        dependency. Coinbase Advanced Trade caps public reads at ~30 req/s
        per IP; even at peak a 6-way fan-out plus the deeper fan-outs in
        `collect_market_context` (8 candles) and `collect_execution_history`
        (4 list calls) stay well under that.
        """
        trace = trace_id or new_id("trace")
        target_coins = coins or ["BTC", "ETH"]
        with ThreadPoolExecutor(max_workers=6, thread_name_prefix="market-collect") as pool:
            f_market = pool.submit(self.provider.collect_market, target_coins)
            f_accounts = pool.submit(self.provider.collect_accounts, target_coins)
            f_portfolio = pool.submit(self.provider.collect_portfolio)
            f_market_ctx = pool.submit(self.provider.collect_market_context, target_coins)
            f_exec_history = pool.submit(self.provider.collect_execution_history, target_coins)
            f_product_meta = pool.submit(self.provider.collect_product_metadata, target_coins)
        # Pool exits only after every submitted task completes — futures are
        # done() at this point so .result() is non-blocking. Any exception
        # is re-raised here; that mirrors the prior serial behavior where
        # the first failing call short-circuited the rest.
        return DataIngestBundle(
            trace_id=trace,
            market=f_market.result(),
            accounts=f_accounts.result(),
            portfolio=f_portfolio.result(),
            market_context=f_market_ctx.result(),
            execution_history=f_exec_history.result(),
            product_metadata=f_product_meta.result(),
        )

    def collect_market_context(
        self,
        *,
        coins: list[str] | None = None,
    ) -> dict[str, MarketContextNormalized]:
        target_coins = coins or ["BTC", "ETH"]
        return self.provider.collect_market_context(target_coins)

    def collect_execution_history(
        self,
        *,
        coins: list[str] | None = None,
    ) -> dict[str, ExecutionHistorySnapshot]:
        target_coins = coins or ["BTC", "ETH"]
        return self.provider.collect_execution_history(target_coins)

    def collect_product_metadata(
        self,
        *,
        coins: list[str] | None = None,
    ) -> dict[str, ProductMetadataSnapshot]:
        target_coins = coins or ["BTC", "ETH"]
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
