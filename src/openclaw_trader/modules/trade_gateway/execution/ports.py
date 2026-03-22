from __future__ import annotations

from typing import Protocol

from .models import ExecutionPlan, ExecutionResult, PortfolioView


class ExecutionBroker(Protocol):
    def execute_plan(self, plan: ExecutionPlan) -> ExecutionResult: ...

    def portfolio(self) -> PortfolioView: ...
