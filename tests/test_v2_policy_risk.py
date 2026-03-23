from __future__ import annotations

import unittest
from pathlib import Path

from openclaw_trader.modules.trade_gateway.execution.models import ExecutionDecision
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

    def test_authorize_execution_injects_default_max_leverage(self) -> None:
        market = DataIngestService(FakeMarketDataProvider()).collect(trace_id="trace-1", coins=["BTC"])
        forecasts = QuantIntelligenceService(FakeQuantProvider(side_12h="long", side_4h="long")).predict_market(market)
        service = PolicyRiskService(build_test_settings(Path("/tmp") / "state" / "test.db"))
        policies = service.evaluate(
            market=market,
            forecasts=forecasts,
            news_events=FakeNewsProvider().latest(),
        )
        authorization = service.authorize_execution(
            strategy_payload=None,
            decisions=[
                ExecutionDecision(
                    decision_id="decision-1",
                    context_id="ctx-1",
                    strategy_version="strategy-1",
                    product_id="BTC-PERP-INTX",
                    coin="BTC",
                    action="open",
                    side="long",
                    size_pct_of_equity=8.0,
                    reason="test",
                )
            ],
            market=market,
            policies=policies,
        )
        self.assertEqual(authorization.rejected, [])
        self.assertEqual(authorization.accepted[0]["leverage"], "5.0")


if __name__ == "__main__":
    unittest.main()
