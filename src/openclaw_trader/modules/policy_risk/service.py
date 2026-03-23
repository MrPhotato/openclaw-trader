from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ...config.models import SystemSettings
from ...shared.protocols import EventFactory
from ...shared.utils import exposure_budget_usd
from ..trade_gateway.execution.models import ExecutionDecision
from ..trade_gateway.market_data.models import DataIngestBundle
from ..news_events.models import NewsDigestEvent
from ..quant_intelligence.models import CoinForecast
from .events import EVENT_EXECUTION_AUTHORIZED, EVENT_EXECUTION_REJECTED, EVENT_RISK_LIMITS_READY, MODULE_NAME
from .models import BreakerState, CooldownState, ExecutionAuthorization, GuardDecision, PolicyDiagnostics, PositionRiskState, RiskLimits, TradeAvailability


class PolicyRiskService:
    def __init__(self, settings: SystemSettings) -> None:
        self.settings = settings

    def get_current_risk_limits(self, *, policies: dict[str, GuardDecision]) -> dict[str, dict]:
        return {
            coin: decision.risk_limits.model_dump(mode="json")
            for coin, decision in policies.items()
        }

    def get_position_risk_state(self, *, policies: dict[str, GuardDecision]) -> dict[str, dict]:
        return {
            coin: decision.position_risk_state.model_dump(mode="json")
            for coin, decision in policies.items()
        }

    def evaluate(
        self,
        *,
        market: DataIngestBundle,
        forecasts: dict[str, CoinForecast],
        news_events: list[NewsDigestEvent],
    ) -> dict[str, GuardDecision]:
        decisions: dict[str, GuardDecision] = {}
        portfolio = market.portfolio
        limits = self._risk_limits()
        total_equity = float(portfolio.total_equity_usd or 0.0)
        total_exposure = float(portfolio.total_exposure_usd or 0.0)
        exposure_budget = float(
            exposure_budget_usd(
                total_equity_usd=portfolio.total_equity_usd,
                max_leverage=limits.max_leverage,
            )
        )
        exposure_pct = (total_exposure / exposure_budget * 100.0) if exposure_budget > 0 else 0.0
        portfolio_drawdown_pct = 0.0
        if float(portfolio.starting_equity_usd or 0.0) > 0:
            portfolio_drawdown_pct = max(
                0.0,
                (float(portfolio.starting_equity_usd or 0.0) - total_equity) / float(portfolio.starting_equity_usd or 1.0) * 100.0,
            )
        recent_event_titles = [item.title for item in news_events[:5]]
        panic_exit = portfolio_drawdown_pct >= 15.0
        breaker_active = panic_exit

        for coin, forecast in forecasts.items():
            snapshot = market.market.get(coin)
            account = market.accounts.get(coin)
            availability_reasons: list[str] = []
            if snapshot is None:
                availability_reasons.append("missing_market_snapshot")
            if account is None:
                availability_reasons.append("missing_account_snapshot")
            if snapshot is not None and snapshot.trading_disabled:
                availability_reasons.append("trading_disabled")
            if snapshot is not None and snapshot.cancel_only:
                availability_reasons.append("cancel_only")
            if total_equity <= 0:
                availability_reasons.append("non_positive_equity")
            if exposure_pct > limits.max_total_exposure_pct_of_equity:
                availability_reasons.append("total_exposure_limit_breached")
            if panic_exit:
                availability_reasons.append("panic_exit")

            position_risk = self._position_risk_state(
                exposure_pct=exposure_pct,
                drawdown_pct=self._position_drawdown_pct(snapshot_mark=snapshot.mark_price if snapshot else None, account=account),
                availability_reasons=availability_reasons,
            )
            cooldown = CooldownState()
            if position_risk.state == "exit":
                cooldown = CooldownState(
                    active=True,
                    until_utc=(datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
                    reason="position_exit",
                )
            breaker = BreakerState()
            if breaker_active or position_risk.state == "breaker":
                breaker = BreakerState(
                    active=True,
                    reason="panic_exit" if panic_exit else "exchange_restriction",
                    until_utc=datetime.now(UTC).replace(hour=23, minute=59, second=59, microsecond=0).isoformat(),
                )
            diagnostics = PolicyDiagnostics(
                recent_event_titles=recent_event_titles,
                horizon_summaries=self._forecast_summary(forecast),
                portfolio_exposure_pct=round(exposure_pct, 4),
            )
            decisions[coin] = GuardDecision(
                coin=coin,
                trade_availability=TradeAvailability(
                    tradable=not availability_reasons and not cooldown.active and not breaker.active,
                    reasons=availability_reasons,
                ),
                risk_limits=limits,
                position_risk_state=position_risk,
                cooldown=cooldown,
                breaker=breaker,
                diagnostics=diagnostics,
                metadata={
                    "event_count": len(news_events),
                    "portfolio_drawdown_pct": round(portfolio_drawdown_pct, 4),
                    "panic_exit": panic_exit,
                },
            )
        return decisions

    def authorize_execution(
        self,
        *,
        strategy_payload: dict | None,
        decisions: list[ExecutionDecision],
        market: DataIngestBundle,
        policies: dict[str, GuardDecision],
    ) -> ExecutionAuthorization:
        accepted: list[dict] = []
        rejected: list[dict] = []
        targets = {
            str(item.get("symbol") or "").upper(): item
            for item in (strategy_payload or {}).get("targets", [])
            if isinstance(item, dict)
        }
        total_equity = float(market.portfolio.total_equity_usd or 0.0)
        for decision in decisions:
            if decision.action in {"wait", "hold"}:
                continue
            policy = policies.get(decision.coin)
            target = targets.get(decision.coin, {})
            reasons: list[str] = []
            if policy is None:
                reasons.append("missing_policy")
            else:
                if not policy.trade_availability.tradable:
                    reasons.extend(policy.trade_availability.reasons or ["not_tradable"])
                if policy.cooldown.active:
                    reasons.append("cooldown_active")
                if policy.breaker.active:
                    reasons.append("breaker_active")
                if decision.size_pct_of_equity and decision.size_pct_of_equity > policy.risk_limits.max_order_pct_of_equity:
                    reasons.append("order_size_limit_breached")
            if decision.action in {"open", "add"} and total_equity <= 0:
                reasons.append("non_positive_equity")
            if reasons:
                rejected.append(
                    {
                        "coin": decision.coin,
                        "decision_id": decision.decision_id,
                        "action": decision.action,
                        "reasons": sorted(set(reasons)),
                    }
                )
                continue
            accepted.append(decision.model_dump(mode="json"))
        return ExecutionAuthorization(accepted=accepted, rejected=rejected)

    def build_policy_events(self, *, trace_id: str, policies: dict[str, GuardDecision]):
        return [
            EventFactory.build(
                trace_id=trace_id,
                event_type=EVENT_RISK_LIMITS_READY,
                source_module=MODULE_NAME,
                entity_type="risk_limits",
                entity_id=coin,
                payload=decision.model_dump(mode="json"),
            )
            for coin, decision in policies.items()
        ]

    def build_execution_authorization_events(self, *, trace_id: str, authorization: ExecutionAuthorization):
        events = []
        for payload in authorization.accepted:
            events.append(
                EventFactory.build(
                    trace_id=trace_id,
                    event_type=EVENT_EXECUTION_AUTHORIZED,
                    source_module=MODULE_NAME,
                    entity_type="execution_authorization",
                    entity_id=str(payload.get("decision_id")),
                    payload=payload,
                )
            )
        for payload in authorization.rejected:
            events.append(
                EventFactory.build(
                    trace_id=trace_id,
                    event_type=EVENT_EXECUTION_REJECTED,
                    source_module=MODULE_NAME,
                    entity_type="execution_authorization",
                    entity_id=str(payload.get("decision_id")),
                    payload=payload,
                )
            )
        return events

    def _risk_limits(self) -> RiskLimits:
        max_symbol = min(
            float(self.settings.risk.max_position_pct_of_equity),
            float(self.settings.execution.max_position_share_pct_of_exposure_budget),
        )
        max_order = min(
            float(self.settings.risk.max_order_pct_of_equity),
            float(self.settings.execution.max_order_share_pct_of_exposure_budget),
        )
        return RiskLimits(
            max_leverage=float(self.settings.execution.max_leverage),
            max_total_exposure_pct_of_equity=float(self.settings.execution.max_total_exposure_pct_of_equity),
            max_symbol_position_pct_of_equity=max_symbol,
            max_order_pct_of_equity=max_order,
        )

    def _position_risk_state(self, *, exposure_pct: float, drawdown_pct: float, availability_reasons: list[str]) -> PositionRiskState:
        thresholds = {
            "observe_drawdown_pct": float(self.settings.risk.position_observe_drawdown_pct),
            "reduce_drawdown_pct": float(self.settings.risk.position_reduce_drawdown_pct),
            "exit_drawdown_pct": float(self.settings.risk.position_exit_drawdown_pct),
        }
        reasons: list[str] = []
        state = "normal"
        if any(reason in {"trading_disabled", "cancel_only"} for reason in availability_reasons):
            state = "breaker"
            reasons.append("exchange_restriction")
        elif drawdown_pct >= thresholds["exit_drawdown_pct"]:
            state = "exit"
            reasons.append("position_drawdown_exit")
        elif drawdown_pct >= thresholds["reduce_drawdown_pct"] or "total_exposure_limit_breached" in availability_reasons:
            state = "reduce"
            reasons.append("reduce_threshold")
        elif drawdown_pct >= thresholds["observe_drawdown_pct"] or exposure_pct > (self.settings.execution.max_total_exposure_pct_of_equity * 0.85):
            state = "observe"
            reasons.append("observe_threshold")
        return PositionRiskState(state=state, reasons=reasons, thresholds=thresholds)

    @staticmethod
    def _forecast_summary(forecast: CoinForecast) -> dict[str, dict[str, float | str]]:
        summary: dict[str, dict[str, float | str]] = {}
        for horizon in ("4h", "12h"):
            signal = forecast.horizons.get(horizon)
            if signal is None:
                continue
            summary[horizon] = {
                "side": signal.side,
                "confidence": round(float(signal.confidence), 4),
            }
        return summary

    @staticmethod
    def _position_drawdown_pct(*, snapshot_mark: str | None, account) -> float:
        if account is None or snapshot_mark is None or account.entry_price is None or account.current_side is None:
            return 0.0
        try:
            entry = float(account.entry_price)
            mark = float(snapshot_mark)
        except Exception:
            return 0.0
        if entry <= 0:
            return 0.0
        side = str(account.current_side).lower()
        if side == "short":
            adverse_move = max(0.0, (mark - entry) / entry * 100.0)
        else:
            adverse_move = max(0.0, (entry - mark) / entry * 100.0)
        return round(adverse_move, 4)
