from __future__ import annotations

from ...shared.protocols import EventFactory
from ...shared.utils import new_id, notional_to_pct_of_exposure_budget
from ..agent_gateway.models import AgentReply
from ..policy_risk.models import GuardDecision
from ..quant_intelligence.models import CoinForecast
from ..trade_gateway.market_data.models import DataIngestBundle
from .events import EVENT_EXECUTION_CONTEXT_BUILT, EVENT_STRATEGY_REFRESHED, MODULE_NAME
from .models import ExecutionContext, StrategyIntent, StrategyTarget


class StrategyIntentService:
    def ensure_strategy(self, *, trace_id: str, reason: str, policies: dict[str, GuardDecision]) -> StrategyIntent:
        targets = [
            StrategyTarget(
                coin=coin,
                product_id=f"{coin}-PERP-INTX",
                bias="neutral",
                target_position_share_pct=0.0,
                max_position_share_pct=decision.risk_limits.max_symbol_position_pct_of_equity,
                rationale="pm_not_run_first_batch",
            )
            for coin, decision in sorted(policies.items())
        ]
        return StrategyIntent(
            strategy_version=f"v2-{new_id('strategy')}",
            change_reason=reason,
            targets=targets,
            thesis="pm_not_run_first_batch",
            invalidation="replace_when_pm_agent_attached",
            scheduled_rechecks=[],
        )

    def merge_pm_reply(self, strategy: StrategyIntent, reply: AgentReply) -> StrategyIntent:
        if reply.status != "completed":
            return strategy
        payload = reply.payload or {}
        thesis = payload.get("thesis")
        if isinstance(thesis, str) and thesis.strip():
            strategy.thesis = thesis.strip()
        return strategy

    def build_execution_contexts(
        self,
        *,
        strategy: StrategyIntent,
        policies: dict[str, GuardDecision],
        market: DataIngestBundle,
        forecasts: dict[str, CoinForecast],
    ) -> list[ExecutionContext]:
        contexts: list[ExecutionContext] = []
        total_equity = float(market.portfolio.total_equity_usd or 0.0)
        for target in strategy.targets:
            account = market.accounts.get(target.coin)
            snapshot = market.market.get(target.coin)
            if account is None or snapshot is None:
                continue
            current_share = notional_to_pct_of_exposure_budget(
                notional_usd=account.current_notional_usd,
                total_equity_usd=total_equity,
                max_leverage=policies[target.coin].risk_limits.max_leverage,
            )
            forecast = forecasts.get(target.coin)
            contexts.append(
                ExecutionContext(
                    context_id=new_id("execctx"),
                    strategy_version=strategy.strategy_version,
                    coin=target.coin,
                    product_id=target.product_id,
                    target_bias=target.bias,
                    target_position_share_pct=target.target_position_share_pct,
                    max_position_share_pct=target.max_position_share_pct,
                    rationale=target.rationale,
                    market_snapshot=snapshot.model_dump(mode="json"),
                    account_snapshot={
                        **account.model_dump(mode="json"),
                        "current_position_share_pct": round(current_share, 4),
                    },
                    risk_limits=policies[target.coin].risk_limits.model_dump(mode="json"),
                    position_risk_state=policies[target.coin].position_risk_state.model_dump(mode="json"),
                    forecast_snapshot=self._forecast_snapshot(forecast),
                    diagnostics={
                        "trade_availability": policies[target.coin].trade_availability.model_dump(mode="json"),
                        "policy_diagnostics": self._policy_diagnostics_snapshot(policies[target.coin]),
                    },
                )
            )
        return contexts

    def build_strategy_event(self, *, trace_id: str, strategy: StrategyIntent):
        return EventFactory.build(
            trace_id=trace_id,
            event_type=EVENT_STRATEGY_REFRESHED,
            source_module=MODULE_NAME,
            entity_type="strategy_intent",
            entity_id=strategy.strategy_version,
            payload=strategy.model_dump(mode="json"),
        )

    def build_execution_context_events(self, *, trace_id: str, execution_contexts: list[ExecutionContext]):
        return [
            EventFactory.build(
                trace_id=trace_id,
                event_type=EVENT_EXECUTION_CONTEXT_BUILT,
                source_module=MODULE_NAME,
                entity_type="execution_context",
                entity_id=context.context_id,
                payload=context.model_dump(mode="json"),
            )
            for context in execution_contexts
        ]

    @staticmethod
    def _forecast_snapshot(forecast: CoinForecast | None) -> dict[str, dict[str, float | str]]:
        if forecast is None:
            return {}
        payload: dict[str, dict[str, float | str]] = {}
        for horizon in ("4h", "12h"):
            signal = forecast.horizons.get(horizon)
            if signal is None:
                continue
            payload[horizon] = {
                "side": signal.side,
                "confidence": round(float(signal.confidence), 4),
            }
        return payload

    @staticmethod
    def _policy_diagnostics_snapshot(decision: GuardDecision) -> dict[str, object]:
        diagnostics = decision.diagnostics.model_dump(mode="json")
        diagnostics.pop("ignored_horizons", None)
        return diagnostics
