from __future__ import annotations

from decimal import Decimal

from .....shared.integrations.coinbase import CoinbaseIntxRuntimeClient
from ..models import ExecutionPlan, ExecutionResult, PortfolioView


class CoinbaseIntxBroker:
    def __init__(self) -> None:
        self.runtime_client = CoinbaseIntxRuntimeClient()

    def execute_plan(self, plan: ExecutionPlan) -> ExecutionResult:
        payload = self.runtime_client.execute_market_order(
            coin=plan.coin,
            action=plan.action,
            side=plan.side,
            notional_usd=Decimal(plan.notional_usd or plan.margin_usd or "0"),
            leverage=Decimal(plan.leverage or str(self.runtime_client.settings.execution.max_leverage)),
        )
        return ExecutionResult(
            plan_id=plan.plan_id,
            success=bool(payload.get("success")),
            exchange_order_id=payload.get("order_id"),
            message=payload.get("message"),
            fills=list(payload.get("fills") or []),
            technical_failure=bool(payload.get("technical_failure", False)),
        )

    def portfolio(self) -> PortfolioView:
        portfolio = self.runtime_client.portfolio()
        return PortfolioView(
            total_equity_usd=portfolio["total_equity_usd"],
            available_equity_usd=portfolio["available_equity_usd"],
            positions=list(portfolio.get("positions") or []),
        )
