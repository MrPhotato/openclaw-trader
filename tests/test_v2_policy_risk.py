from __future__ import annotations

import unittest
from pathlib import Path

from openclaw_trader.modules.trade_gateway.market_data.service import DataIngestService
from openclaw_trader.modules.policy_risk.service import PolicyRiskService
from openclaw_trader.modules.quant_intelligence.service import QuantIntelligenceService

from .helpers_v2 import FakeMarketDataProvider, FakeNewsProvider, FakeQuantProvider, build_test_settings


class PolicyRiskServiceTests(unittest.TestCase):
    def test_policy_risk_only_exposes_hard_limits_and_ignores_1h(self) -> None:
        market = DataIngestService(FakeMarketDataProvider()).collect(trace_id="trace-1", coins=["BTC"])
        forecasts = QuantIntelligenceService(FakeQuantProvider(side_12h="long", side_4h="long")).predict_market(market)
        decisions = PolicyRiskService(build_test_settings(Path("/tmp") / "state" / "test.db")).evaluate(
            market=market,
            forecasts=forecasts,
            news_events=FakeNewsProvider().latest(),
        )
        self.assertTrue(decisions["BTC"].trade_availability.tradable)
        self.assertFalse(hasattr(decisions["BTC"], "shadow_policy"))
        self.assertEqual(decisions["BTC"].diagnostics.ignored_horizons, ["1h"])
        self.assertEqual(decisions["BTC"].diagnostics.portfolio_exposure_pct, 4.0)


if __name__ == "__main__":
    unittest.main()
