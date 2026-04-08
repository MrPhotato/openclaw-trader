from __future__ import annotations

from decimal import Decimal

from ....shared.protocols import EventFactory
from ....shared.utils import new_id, pct_to_notional_usd
from .events import EVENT_EXECUTION_COMPLETED, EVENT_EXECUTION_PLAN_BUILT, MODULE_NAME
from .models import ExecutionDecision, ExecutionPlan, ExecutionResult, PortfolioView
from .ports import ExecutionBroker


class ExecutionGatewayService:
    def __init__(self, broker: ExecutionBroker, *, live_enabled: bool = False) -> None:
        self.broker = broker
        self.live_enabled = live_enabled

    def build_execution_plans(
        self,
        *,
        decisions: list[ExecutionDecision],
        total_equity_usd: str | None = None,
        max_leverage: str | float | None = None,
        max_notional_usd: float | None = None,
    ) -> list[ExecutionPlan]:
        plans: list[ExecutionPlan] = []
        for decision in decisions:
            if decision.action in {"wait", "hold"}:
                continue
            notional_usd = decision.notional_usd
            if not notional_usd and decision.size_pct_of_exposure_budget is not None:
                notional_value = pct_to_notional_usd(
                    pct_of_exposure_budget=decision.size_pct_of_exposure_budget,
                    total_equity_usd=total_equity_usd,
                    max_leverage=max_leverage,
                )
                if max_notional_usd is not None:
                    notional_value = min(notional_value, Decimal(str(max_notional_usd)))
                notional_usd = str(round(notional_value, 8))
            plans.append(
                ExecutionPlan(
                    plan_id=new_id("plan"),
                    decision_id=decision.decision_id,
                    context_id=decision.context_id,
                    strategy_version=decision.strategy_version,
                    product_id=decision.product_id,
                    coin=decision.coin,
                    action=decision.action,
                    side=decision.side,
                    size_pct_of_exposure_budget=decision.size_pct_of_exposure_budget,
                    margin_usd=notional_usd,
                    notional_usd=notional_usd,
                    leverage=decision.leverage,
                    preflight={
                        "urgency": decision.urgency,
                        "valid_for_minutes": decision.valid_for_minutes,
                    },
                )
            )
        return plans

    def execute(self, plans: list[ExecutionPlan], *, live: bool = False) -> list[ExecutionResult]:
        if not live or not self.live_enabled:
            return [
                ExecutionResult(
                    plan_id=plan.plan_id,
                    decision_id=plan.decision_id,
                    strategy_version=plan.strategy_version,
                    coin=plan.coin,
                    action=plan.action,
                    side=plan.side,
                    notional_usd=plan.notional_usd,
                    success=True,
                    message="simulated_execution",
                    fills=[],
                )
                for plan in plans
            ]
        results: list[ExecutionResult] = []
        for plan in plans:
            payload = self.broker.execute_plan(plan)
            results.append(
                ExecutionResult(
                    plan_id=plan.plan_id,
                    decision_id=plan.decision_id,
                    strategy_version=plan.strategy_version,
                    coin=plan.coin,
                    action=plan.action,
                    side=plan.side,
                    notional_usd=plan.notional_usd,
                    success=payload.success,
                    exchange_order_id=payload.exchange_order_id,
                    message=payload.message,
                    fills=payload.fills,
                    executed_at=payload.executed_at,
                    technical_failure=payload.technical_failure,
                )
            )
        return results

    def current_portfolio(self) -> dict:
        return self.broker.portfolio().model_dump(mode="json")

    def build_plan_events(self, *, trace_id: str, plans: list[ExecutionPlan]):
        return [
            EventFactory.build(
                trace_id=trace_id,
                event_type=EVENT_EXECUTION_PLAN_BUILT,
                source_module=MODULE_NAME,
                entity_type="execution_plan",
                entity_id=plan.plan_id,
                payload=plan.model_dump(mode="json"),
            )
            for plan in plans
        ]

    def build_result_events(self, *, trace_id: str, results: list[ExecutionResult]):
        return [
            EventFactory.build(
                trace_id=trace_id,
                event_type=EVENT_EXECUTION_COMPLETED,
                source_module=MODULE_NAME,
                entity_type="execution_result",
                entity_id=result.plan_id,
                payload=result.model_dump(mode="json"),
            )
            for result in results
        ]
