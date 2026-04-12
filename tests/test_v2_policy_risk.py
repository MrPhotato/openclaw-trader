from __future__ import annotations

import unittest
from datetime import UTC, datetime
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
        self.assertEqual(decisions["BTC"].diagnostics.portfolio_exposure_pct_of_exposure_budget, 4.0)

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
                    size_pct_of_exposure_budget=8.0,
                    reason="test",
                )
            ],
            market=market,
            policies=policies,
        )
        self.assertEqual(authorization.rejected, [])
        self.assertEqual(authorization.accepted[0]["leverage"], "5.0")

    def test_daily_loss_limit_uses_config_for_panic_exit(self) -> None:
        market = DataIngestService(FakeMarketDataProvider()).collect(trace_id="trace-1", coins=["BTC"])
        market = market.model_copy(
            update={
                "portfolio": market.portfolio.model_copy(
                    update={
                        "starting_equity_usd": "1000",
                        "total_equity_usd": "940",
                    }
                )
            }
        )
        forecasts = QuantIntelligenceService(FakeQuantProvider(side_12h="long", side_4h="long")).predict_market(market)
        settings = build_test_settings(Path("/tmp") / "state" / "test.db")
        settings = settings.model_copy(
            update={
                "risk": settings.risk.model_copy(
                    update={
                        "daily_loss_limit_pct_of_equity": 5.0,
                        "emergency_exit_enabled": True,
                    }
                )
            }
        )
        policies = PolicyRiskService(settings).evaluate(
            market=market,
            forecasts=forecasts,
            news_events=FakeNewsProvider().latest(),
        )

        self.assertFalse(policies["BTC"].trade_availability.tradable)
        self.assertIn("panic_exit", policies["BTC"].trade_availability.reasons)
        self.assertTrue(policies["BTC"].breaker.active)
        self.assertEqual(policies["BTC"].breaker.reason, "panic_exit")
        self.assertEqual(policies["BTC"].metadata["daily_loss_limit_pct_of_equity"], 5.0)
        self.assertTrue(policies["BTC"].metadata["panic_exit"])

    def test_daily_loss_limit_respects_emergency_exit_switch(self) -> None:
        market = DataIngestService(FakeMarketDataProvider()).collect(trace_id="trace-1", coins=["BTC"])
        market = market.model_copy(
            update={
                "portfolio": market.portfolio.model_copy(
                    update={
                        "starting_equity_usd": "1000",
                        "total_equity_usd": "940",
                    }
                )
            }
        )
        forecasts = QuantIntelligenceService(FakeQuantProvider(side_12h="long", side_4h="long")).predict_market(market)
        settings = build_test_settings(Path("/tmp") / "state" / "test.db")
        settings = settings.model_copy(
            update={
                "risk": settings.risk.model_copy(
                    update={
                        "daily_loss_limit_pct_of_equity": 5.0,
                        "emergency_exit_enabled": False,
                    }
                )
            }
        )
        policies = PolicyRiskService(settings).evaluate(
            market=market,
            forecasts=forecasts,
            news_events=FakeNewsProvider().latest(),
        )

        self.assertTrue(policies["BTC"].trade_availability.tradable)
        self.assertFalse(policies["BTC"].breaker.active)
        self.assertFalse(policies["BTC"].metadata["panic_exit"])

    def test_position_drawdown_uses_trailing_peak_for_long_positions(self) -> None:
        market = DataIngestService(FakeMarketDataProvider()).collect(trace_id="trace-1", coins=["BTC"])
        market = market.model_copy(
            update={
                "market": {
                    **market.market,
                    "BTC": market.market["BTC"].model_copy(update={"mark_price": "110"}),
                }
            }
        )
        forecasts = QuantIntelligenceService(FakeQuantProvider()).predict_market(market)
        service = PolicyRiskService(build_test_settings(Path("/tmp") / "state" / "test.db"))
        policies = service.evaluate(
            market=market,
            forecasts=forecasts,
            news_events=[],
            prior_risk_state={
                "portfolio_day_utc": datetime.now(UTC).date().isoformat(),
                "portfolio_day_peak_equity_usd": "1000",
                "position_references_by_coin": {
                    "BTC": {
                        "side": "long",
                        "reference_price": "120",
                        "reference_kind": "peak",
                    }
                },
            },
            latest_strategy={},
        )

        self.assertEqual(policies["BTC"].position_risk_state.reference_price, "120")
        self.assertAlmostEqual(policies["BTC"].position_risk_state.drawdown_pct, 8.3333, places=3)
        self.assertEqual(policies["BTC"].position_risk_state.state, "exit")

    def test_portfolio_peak_drawdown_enters_reduce_state(self) -> None:
        market = DataIngestService(FakeMarketDataProvider()).collect(trace_id="trace-1", coins=["BTC"])
        forecasts = QuantIntelligenceService(FakeQuantProvider()).predict_market(market)
        service = PolicyRiskService(build_test_settings(Path("/tmp") / "state" / "test.db"))
        policies = service.evaluate(
            market=market,
            forecasts=forecasts,
            news_events=[],
            prior_risk_state={
                "portfolio_day_utc": datetime.now(UTC).date().isoformat(),
                "portfolio_day_peak_equity_usd": "1030",
            },
            latest_strategy={},
        )

        portfolio_risk_state = policies["BTC"].portfolio_risk_state
        self.assertEqual(portfolio_risk_state.state, "reduce")
        self.assertAlmostEqual(portfolio_risk_state.drawdown_pct, 2.9126, places=3)

    def test_reduce_only_lock_blocks_add_until_new_strategy_revision(self) -> None:
        market = DataIngestService(FakeMarketDataProvider()).collect(trace_id="trace-1", coins=["BTC"])
        forecasts = QuantIntelligenceService(FakeQuantProvider()).predict_market(market)
        service = PolicyRiskService(build_test_settings(Path("/tmp") / "state" / "test.db"))
        current_strategy = {"strategy_id": "strategy-1", "revision_number": 1}
        locked_policies = service.evaluate(
            market=market,
            forecasts=forecasts,
            news_events=[],
            prior_risk_state={
                "portfolio_day_utc": datetime.now(UTC).date().isoformat(),
                "portfolio_day_peak_equity_usd": "1000",
                "portfolio_lock": {
                    "mode": "reduce_only",
                    "strategy_key": "strategy-1:1",
                },
            },
            latest_strategy=current_strategy,
        )
        blocked = service.authorize_execution(
            strategy_payload=current_strategy,
            decisions=[
                ExecutionDecision(
                    decision_id="decision-1",
                    context_id="ctx-1",
                    strategy_version="strategy-1",
                    product_id="BTC-PERP-INTX",
                    coin="BTC",
                    action="add",
                    side="long",
                    size_pct_of_exposure_budget=4.0,
                    reason="locked",
                )
            ],
            market=market,
            policies=locked_policies,
        )
        self.assertEqual(blocked.accepted, [])
        self.assertIn("portfolio_lock_reduce_only", blocked.rejected[0]["reasons"])

        unlocked_policies = service.evaluate(
            market=market,
            forecasts=forecasts,
            news_events=[],
            prior_risk_state={
                "portfolio_day_utc": datetime.now(UTC).date().isoformat(),
                "portfolio_day_peak_equity_usd": "1000",
                "portfolio_lock": {
                    "mode": "reduce_only",
                    "strategy_key": "strategy-1:1",
                },
            },
            latest_strategy={"strategy_id": "strategy-2", "revision_number": 2},
        )
        allowed = service.authorize_execution(
            strategy_payload={"strategy_id": "strategy-2", "revision_number": 2},
            decisions=[
                ExecutionDecision(
                    decision_id="decision-2",
                    context_id="ctx-2",
                    strategy_version="strategy-2",
                    product_id="BTC-PERP-INTX",
                    coin="BTC",
                    action="add",
                    side="long",
                    size_pct_of_exposure_budget=4.0,
                    reason="unlocked",
                )
            ],
            market=market,
            policies=unlocked_policies,
        )
        self.assertEqual(allowed.rejected, [])
        self.assertEqual(len(allowed.accepted), 1)


if __name__ == "__main__":
    unittest.main()
