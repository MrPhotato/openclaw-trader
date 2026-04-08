from __future__ import annotations

import unittest
from pathlib import Path

from openclaw_trader.modules.trade_gateway.market_data.service import DataIngestService
from openclaw_trader.modules.policy_risk.service import PolicyRiskService
from openclaw_trader.modules.quant_intelligence.service import QuantIntelligenceService
from openclaw_trader.modules.strategy_intent.service import StrategyIntentService

from .helpers_v2 import FakeMarketDataProvider, FakeNewsProvider, FakeQuantProvider, build_test_settings


class StrategyIntentServiceTests(unittest.TestCase):
    def test_builds_execution_contexts_without_candidates(self) -> None:
        market = DataIngestService(FakeMarketDataProvider()).collect(trace_id="trace-1", coins=["BTC"])
        forecasts = QuantIntelligenceService(FakeQuantProvider()).predict_market(market)
        policies = PolicyRiskService(build_test_settings(Path("/tmp") / "state" / "test.db")).evaluate(
            market=market,
            forecasts=forecasts,
            news_events=FakeNewsProvider().latest(),
        )
        strategy = StrategyIntentService().ensure_strategy(trace_id="trace-1", reason="dispatch_once", policies=policies)
        contexts = StrategyIntentService().build_execution_contexts(
            strategy=strategy,
            policies=policies,
            market=market,
            forecasts=forecasts,
        )
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0].target_position_pct_of_exposure_budget, 0.0)
        self.assertEqual(set(contexts[0].forecast_snapshot), {"4h", "12h"})


if __name__ == "__main__":
    unittest.main()
