from __future__ import annotations

import time
import unittest
from threading import Lock

from openclaw_trader.modules.trade_gateway.market_data.service import DataIngestService

from .helpers_v2 import FakeMarketDataProvider


class _SlowProvider(FakeMarketDataProvider):
    """Adds a fixed sleep to every provider method, with concurrency tracking.

    Used to detect whether DataIngestService.collect() actually fans out — a
    serial implementation would record max_concurrent=1 and wall time near
    6 × delay; a parallel one records max_concurrent>=2 and wall time near
    delay.
    """

    def __init__(self, *, delay_seconds: float = 0.1) -> None:
        super().__init__()
        self._delay = float(delay_seconds)
        self._lock = Lock()
        self._active = 0
        self.max_concurrent = 0

    def _enter(self) -> None:
        with self._lock:
            self._active += 1
            if self._active > self.max_concurrent:
                self.max_concurrent = self._active
        time.sleep(self._delay)
        with self._lock:
            self._active -= 1

    def collect_market(self, coins):  # type: ignore[override]
        self._enter()
        return super().collect_market(coins)

    def collect_accounts(self, coins):  # type: ignore[override]
        self._enter()
        return super().collect_accounts(coins)

    def collect_portfolio(self):  # type: ignore[override]
        self._enter()
        return super().collect_portfolio()

    def collect_market_context(self, coins):  # type: ignore[override]
        self._enter()
        return super().collect_market_context(coins)

    def collect_execution_history(self, coins):  # type: ignore[override]
        self._enter()
        return super().collect_execution_history(coins)

    def collect_product_metadata(self, coins):  # type: ignore[override]
        self._enter()
        return super().collect_product_metadata(coins)


class DataIngestServiceTests(unittest.TestCase):
    def test_collect_returns_bundle_and_events(self) -> None:
        service = DataIngestService(FakeMarketDataProvider())
        bundle = service.collect(trace_id="trace-1", coins=["BTC"])
        events = service.build_market_events(bundle)
        self.assertIn("BTC", bundle.market)
        self.assertIn("BTC", bundle.market_context)
        self.assertIn("BTC", bundle.execution_history)
        self.assertIn("BTC", bundle.product_metadata)
        self.assertEqual(bundle.portfolio.total_equity_usd, "1000")
        self.assertEqual(len(events), 2)

    def test_collects_extended_market_context_and_execution_history(self) -> None:
        service = DataIngestService(FakeMarketDataProvider())
        contexts = service.collect_market_context(coins=["BTC"])
        history = service.collect_execution_history(coins=["BTC"])
        metadata = service.collect_product_metadata(coins=["BTC"])
        self.assertIn("BTC", contexts)
        self.assertIn("15m", contexts["BTC"].compressed_price_series)
        self.assertIn("BTC", history)
        self.assertTrue(history["BTC"].recent_orders)
        self.assertTrue(history["BTC"].open_orders)
        self.assertIn("BTC", metadata)
        self.assertEqual(metadata["BTC"].min_notional, "10")

    def test_collect_fans_out_six_provider_calls_in_parallel(self) -> None:
        """Regression: prior to 2026-04-25 collect() ran the 6 provider
        calls serially. With each Coinbase HTTP at 1-3s the bridge cycle
        stretched to 14-23s. ThreadPoolExecutor must now run them in
        parallel (max_concurrent >= 2 and wall time well below the serial
        sum).
        """
        provider = _SlowProvider(delay_seconds=0.15)
        service = DataIngestService(provider)
        t0 = time.monotonic()
        bundle = service.collect(trace_id="trace-1", coins=["BTC"])
        wall = time.monotonic() - t0
        self.assertIsNotNone(bundle.market)
        # Serial would be 6 × 0.15s = 0.9s. Parallel should land near 0.15s
        # plus pool overhead. Generous ceiling at 0.6s catches a regression
        # to serial without flaking on slow CI.
        self.assertLess(
            wall, 0.6,
            f"collect() wall time {wall:.2f}s suggests serial fan-out (expected near {provider._delay:.2f}s)",
        )
        self.assertGreaterEqual(
            provider.max_concurrent, 2,
            "Expected at least two provider methods to overlap",
        )


if __name__ == "__main__":
    unittest.main()
