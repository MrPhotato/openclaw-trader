from __future__ import annotations

import unittest

from openclaw_trader.modules.trade_gateway.market_data.service import DataIngestService

from .helpers_v2 import FakeMarketDataProvider


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


if __name__ == "__main__":
    unittest.main()
