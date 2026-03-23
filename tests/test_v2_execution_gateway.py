from __future__ import annotations

import unittest
from datetime import UTC, datetime

from openclaw_trader.modules.trade_gateway.execution import ExecutionDecision, ExecutionResult
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

    def test_execute_preserves_non_technical_broker_failure(self) -> None:
        class BusinessRejectingBroker:
            def execute_plan(self, plan):
                return ExecutionResult(
                    plan_id=plan.plan_id,
                    decision_id=plan.decision_id,
                    strategy_version=plan.strategy_version,
                    coin=plan.coin,
                    action=plan.action,
                    side=plan.side,
                    notional_usd=plan.notional_usd,
                    success=False,
                    message="PREVIEW_INSUFFICIENT_FUNDS_FOR_FUTURES",
                    fills=[],
                    executed_at=datetime.now(UTC),
                    technical_failure=False,
                )

            def portfolio(self):
                raise NotImplementedError

        service = ExecutionGatewayService(BusinessRejectingBroker(), live_enabled=True)
        plans = service.build_execution_plans(
            decisions=[
                ExecutionDecision(
                    decision_id="d4",
                    context_id="ctx-4",
                    strategy_version="v1",
                    product_id="ETH-PERP-INTX",
                    coin="ETH",
                    action="open",
                    side="long",
                    notional_usd="400",
                    leverage="5",
                    reason="test",
                )
            ]
        )
        results = service.execute(plans, live=True)
        self.assertFalse(results[0].success)
        self.assertEqual(results[0].message, "PREVIEW_INSUFFICIENT_FUNDS_FOR_FUTURES")
        self.assertFalse(results[0].technical_failure)


if __name__ == "__main__":
    unittest.main()
