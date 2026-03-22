from __future__ import annotations

from typing import Protocol

from ..quant_intelligence.models import CoinForecast
from ..trade_gateway.market_data.models import DataIngestBundle
from ..policy_risk.models import GuardDecision
from .models import ExecutionContext, StrategyIntent


class StrategyPlanner(Protocol):
    def build_strategy(self, *, trace_id: str, reason: str, policies: dict[str, GuardDecision]) -> StrategyIntent: ...

    def build_execution_contexts(
        self,
        *,
        strategy: StrategyIntent,
        policies: dict[str, GuardDecision],
        market: DataIngestBundle,
        forecasts: dict[str, CoinForecast],
    ) -> list[ExecutionContext]: ...
