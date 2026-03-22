from __future__ import annotations

import unittest

from openclaw_trader.modules.trade_gateway.execution import ExecutionDecision
from openclaw_trader.modules.trade_gateway.execution.service import ExecutionGatewayService

from .helpers_v2 import FakeBroker


class ExecutionGatewayServiceTests(unittest.TestCase):
    def test_build_plan_and_execute(self) -> None:
        service = ExecutionGatewayService(FakeBroker())
        decision = ExecutionDecision(
            decision_id="d1",
            context_id="ctx-1",
            strategy_version="v1",
            product_id="BTC-PERP-INTX",
            coin="BTC",
            action="open",
            side="long",
            notional_usd="100",
            leverage="2",
            reason="test",
        )
        plans = service.build_execution_plans(decisions=[decision])
        results = service.execute(plans)
        self.assertEqual(len(plans), 1)
        self.assertTrue(results[0].success)

    def test_size_pct_uses_exposure_budget_denominator(self) -> None:
        service = ExecutionGatewayService(FakeBroker())
        decision = ExecutionDecision(
            decision_id="d2",
            context_id="ctx-2",
            strategy_version="v1",
            product_id="BTC-PERP-INTX",
            coin="BTC",
            action="open",
            side="long",
            size_pct_of_equity=20.0,
            leverage="2",
            reason="budget-test",
        )
        plans = service.build_execution_plans(
            decisions=[decision],
            total_equity_usd="1000",
            max_leverage=5,
        )
        self.assertEqual(plans[0].notional_usd, "1000.00000000")

    def test_hold_decision_builds_no_execution_plan(self) -> None:
        service = ExecutionGatewayService(FakeBroker())
        decision = ExecutionDecision(
            decision_id="d3",
            context_id="ctx-3",
            strategy_version="v1",
            product_id="BTC-PERP-INTX",
            coin="BTC",
            action="hold",
            side="long",
            reason="keep current position",
        )
        plans = service.build_execution_plans(decisions=[decision])
        self.assertEqual(plans, [])


if __name__ == "__main__":
    unittest.main()
