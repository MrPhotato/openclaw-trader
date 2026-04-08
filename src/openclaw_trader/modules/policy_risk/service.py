from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from ...config.models import SystemSettings
from ...shared.protocols import EventFactory
from ...shared.utils import exposure_budget_usd
from ..news_events.models import NewsDigestEvent
from ..quant_intelligence.models import CoinForecast
from ..trade_gateway.execution.models import ExecutionDecision
from ..trade_gateway.market_data.models import AccountSnapshot, DataIngestBundle
from .events import (
    EVENT_EXECUTION_AUTHORIZED,
    EVENT_EXECUTION_REJECTED,
    EVENT_RISK_LIMITS_READY,
    MODULE_NAME,
)
from .models import (
    BreakerState,
    CooldownState,
    ExecutionAuthorization,
    GuardDecision,
    PolicyDiagnostics,
    PortfolioRiskState,
    PositionRiskState,
    RiskLimits,
    TradeAvailability,
)


_LOCK_PRECEDENCE = {"normal": 0, "reduce_only": 1, "flat_only": 2}
_REDUCE_ALLOWED_ACTIONS = {"reduce", "close", "hold", "wait"}
_FLAT_ALLOWED_ACTIONS = {"close", "hold", "wait"}
_RISK_REDUCING_ACTIONS = {"reduce", "close", "hold", "wait"}
_HARD_REDUCTION_BLOCKERS = {
    "missing_market_snapshot",
    "missing_account_snapshot",
    "trading_disabled",
    "cancel_only",
}


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
        prior_risk_state: dict[str, Any] | None = None,
        latest_strategy: dict[str, Any] | None = None,
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
        exposure_pct_of_exposure_budget = (total_exposure / exposure_budget * 100.0) if exposure_budget > 0 else 0.0
        portfolio_drawdown_pct = 0.0
        if float(portfolio.starting_equity_usd or 0.0) > 0:
            portfolio_drawdown_pct = max(
                0.0,
                (float(portfolio.starting_equity_usd or 0.0) - total_equity)
                / float(portfolio.starting_equity_usd or 1.0)
                * 100.0,
            )
        recent_event_titles = [item.title for item in news_events[:5]]
        daily_loss_limit_pct = float(self.settings.risk.daily_loss_limit_pct_of_equity)
        panic_exit = (
            bool(self.settings.risk.emergency_exit_enabled)
            and daily_loss_limit_pct > 0
            and portfolio_drawdown_pct >= daily_loss_limit_pct
        )
        breaker_active = panic_exit
        current_strategy_key = self._strategy_key(latest_strategy)
        risk_state = self._normalize_risk_state(
            prior_state=prior_risk_state,
            current_strategy_key=current_strategy_key,
        )
        portfolio_risk_state = self._portfolio_risk_state(
            total_equity=total_equity,
            risk_state=risk_state,
        )
        coins = sorted(set(market.market.keys()) | set(market.accounts.keys()) | set(forecasts.keys()))
        for coin in coins:
            forecast = forecasts.get(coin)
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
            if exposure_pct_of_exposure_budget > limits.max_total_exposure_pct_of_exposure_budget:
                availability_reasons.append("total_exposure_limit_breached")
            if panic_exit:
                availability_reasons.append("panic_exit")

            peak_context = self._position_peak_context(
                coin=coin,
                snapshot_mark=snapshot.mark_price if snapshot is not None else None,
                account=account,
                risk_state=risk_state,
            )
            position_risk = self._position_risk_state(
                exposure_pct_of_exposure_budget=exposure_pct_of_exposure_budget,
                drawdown_pct=peak_context["drawdown_pct"],
                availability_reasons=availability_reasons,
                reference_price=peak_context["reference_price"],
                reference_kind=peak_context["reference_kind"],
                current_mark_price=snapshot.mark_price if snapshot is not None else None,
                lock_mode=self._position_lock_mode(coin=coin, risk_state=risk_state),
                lock_strategy_key=self._position_lock_strategy_key(coin=coin, risk_state=risk_state),
            )
            cooldown = CooldownState()
            breaker = BreakerState()
            if breaker_active or position_risk.state == "breaker":
                breaker = BreakerState(
                    active=True,
                    reason="panic_exit" if panic_exit else "exchange_restriction",
                    until_utc=datetime.now(UTC).replace(
                        hour=23,
                        minute=59,
                        second=59,
                        microsecond=0,
                    ).isoformat(),
                )
            diagnostics = PolicyDiagnostics(
                recent_event_titles=recent_event_titles,
                horizon_summaries=self._forecast_summary(forecast),
                portfolio_exposure_pct_of_exposure_budget=round(exposure_pct_of_exposure_budget, 4),
            )
            decisions[coin] = GuardDecision(
                coin=coin,
                trade_availability=TradeAvailability(
                    tradable=not availability_reasons,
                    reasons=availability_reasons,
                ),
                risk_limits=limits,
                position_risk_state=position_risk,
                portfolio_risk_state=portfolio_risk_state,
                cooldown=cooldown,
                breaker=breaker,
                diagnostics=diagnostics,
                metadata={
                    "event_count": len(news_events),
                    "portfolio_drawdown_pct": round(portfolio_drawdown_pct, 4),
                    "portfolio_peak_drawdown_pct": round(portfolio_risk_state.drawdown_pct, 4),
                    "portfolio_day_peak_equity_usd": portfolio_risk_state.day_peak_equity_usd,
                    "daily_loss_limit_pct_of_equity": daily_loss_limit_pct,
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
        total_equity = float(market.portfolio.total_equity_usd or 0.0)
        for decision in decisions:
            if decision.action in {"wait", "hold"}:
                continue
            policy = policies.get(decision.coin)
            reasons: list[str] = []
            risk_reducing = self._is_risk_reducing_action(decision.action)
            if policy is None:
                reasons.append("missing_policy")
            else:
                availability_reasons = list(policy.trade_availability.reasons or [])
                if risk_reducing:
                    reasons.extend(
                        reason
                        for reason in availability_reasons
                        if reason in _HARD_REDUCTION_BLOCKERS
                    )
                else:
                    if not policy.trade_availability.tradable:
                        reasons.extend(availability_reasons or ["not_tradable"])
                    if policy.cooldown.active:
                        reasons.append("cooldown_active")
                    if policy.breaker.active:
                        reasons.append("breaker_active")
                lock_mode = self._combine_lock_modes(
                    portfolio_mode=policy.portfolio_risk_state.lock_mode,
                    position_mode=policy.position_risk_state.lock_mode,
                )
                violation = self._lock_violation_reason(lock_mode=lock_mode, action=decision.action)
                if violation is not None:
                    reasons.append(violation)
                if (
                    not risk_reducing
                    and decision.size_pct_of_exposure_budget
                    and decision.size_pct_of_exposure_budget > policy.risk_limits.max_order_pct_of_exposure_budget
                ):
                    reasons.append("order_size_limit_breached")
            if decision.action in {"open", "add", "flip"} and total_equity <= 0:
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
            accepted_payload = decision.model_dump(mode="json")
            if policy is not None:
                accepted_payload["leverage"] = self._effective_execution_leverage(
                    requested=decision.leverage,
                    max_allowed=policy.risk_limits.max_leverage,
                )
            accepted.append(accepted_payload)
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
            float(self.settings.risk.max_position_pct_of_exposure_budget),
            float(self.settings.execution.max_position_pct_of_exposure_budget),
        )
        max_order = min(
            float(self.settings.risk.max_order_pct_of_exposure_budget),
            float(self.settings.execution.max_order_pct_of_exposure_budget),
        )
        return RiskLimits(
            max_leverage=float(self.settings.execution.max_leverage),
            max_total_exposure_pct_of_exposure_budget=float(
                self.settings.execution.max_total_exposure_pct_of_exposure_budget
            ),
            max_symbol_position_pct_of_exposure_budget=max_symbol,
            max_order_pct_of_exposure_budget=max_order,
        )

    def _position_risk_state(
        self,
        *,
        exposure_pct_of_exposure_budget: float,
        drawdown_pct: float,
        availability_reasons: list[str],
        reference_price: str | None,
        reference_kind: str | None,
        current_mark_price: str | None,
        lock_mode: str | None,
        lock_strategy_key: str | None,
    ) -> PositionRiskState:
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
            reasons.append("position_peak_exit")
        elif drawdown_pct >= thresholds["reduce_drawdown_pct"] or "total_exposure_limit_breached" in availability_reasons:
            state = "reduce"
            reasons.append("position_peak_reduce")
        elif drawdown_pct >= thresholds["observe_drawdown_pct"] or exposure_pct_of_exposure_budget > (
            self.settings.execution.max_total_exposure_pct_of_exposure_budget * 0.85
        ):
            state = "observe"
            reasons.append("position_peak_observe")
        return PositionRiskState(
            state=state,
            reasons=reasons,
            thresholds=thresholds,
            drawdown_pct=round(drawdown_pct, 4),
            reference_price=reference_price,
            reference_kind=reference_kind,
            current_mark_price=current_mark_price,
            lock_mode=lock_mode,
            lock_strategy_key=lock_strategy_key,
        )

    def _portfolio_risk_state(
        self,
        *,
        total_equity: float,
        risk_state: dict[str, Any],
    ) -> PortfolioRiskState:
        thresholds = {
            "observe_drawdown_pct": float(self.settings.risk.portfolio_peak_observe_drawdown_pct),
            "reduce_drawdown_pct": float(self.settings.risk.portfolio_peak_reduce_drawdown_pct),
            "exit_drawdown_pct": float(self.settings.risk.portfolio_peak_exit_drawdown_pct),
        }
        peak_equity = max(float(risk_state.get("portfolio_day_peak_equity_usd") or 0.0), total_equity, 0.0)
        drawdown_pct = 0.0
        if peak_equity > 0:
            drawdown_pct = max(0.0, (peak_equity - total_equity) / peak_equity * 100.0)
        reasons: list[str] = []
        state = "normal"
        if drawdown_pct >= thresholds["exit_drawdown_pct"]:
            state = "exit"
            reasons.append("portfolio_peak_exit")
        elif drawdown_pct >= thresholds["reduce_drawdown_pct"]:
            state = "reduce"
            reasons.append("portfolio_peak_reduce")
        elif drawdown_pct >= thresholds["observe_drawdown_pct"]:
            state = "observe"
            reasons.append("portfolio_peak_observe")
        portfolio_lock = dict(risk_state.get("portfolio_lock") or {})
        return PortfolioRiskState(
            state=state,
            reasons=reasons,
            thresholds=thresholds,
            drawdown_pct=round(drawdown_pct, 4),
            current_equity_usd=str(round(total_equity, 8)),
            day_peak_equity_usd=str(round(peak_equity, 8)),
            portfolio_day_utc=str(risk_state.get("portfolio_day_utc") or ""),
            lock_mode=str(portfolio_lock.get("mode") or "") or None,
            lock_strategy_key=str(portfolio_lock.get("strategy_key") or "") or None,
        )

    @staticmethod
    def _forecast_summary(forecast: CoinForecast | None) -> dict[str, dict[str, float | str]]:
        if forecast is None:
            return {}
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

    def _normalize_risk_state(
        self,
        *,
        prior_state: dict[str, Any] | None,
        current_strategy_key: str,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        state = dict(prior_state or {})
        portfolio_day_utc = str(state.get("portfolio_day_utc") or now.date().isoformat())
        if portfolio_day_utc != now.date().isoformat():
            state["portfolio_day_utc"] = now.date().isoformat()
            state["portfolio_day_peak_equity_usd"] = "0"
        state["portfolio_day_utc"] = now.date().isoformat()

        portfolio_lock = dict(state.get("portfolio_lock") or {})
        if portfolio_lock and current_strategy_key and str(portfolio_lock.get("strategy_key") or "") != current_strategy_key:
            state["portfolio_lock"] = {}

        position_locks: dict[str, dict[str, Any]] = {}
        for coin, payload in dict(state.get("position_locks") or {}).items():
            item = dict(payload or {})
            if current_strategy_key and str(item.get("strategy_key") or "") != current_strategy_key:
                continue
            position_locks[str(coin).upper()] = item
        state["position_locks"] = position_locks
        return state

    def _position_peak_context(
        self,
        *,
        coin: str,
        snapshot_mark: str | None,
        account: AccountSnapshot | None,
        risk_state: dict[str, Any],
    ) -> dict[str, Any]:
        if account is None or snapshot_mark is None or account.entry_price is None or account.current_side is None:
            return {
                "drawdown_pct": 0.0,
                "reference_price": None,
                "reference_kind": None,
            }
        side = str(account.current_side or "").lower()
        if side not in {"long", "short"}:
            return {
                "drawdown_pct": 0.0,
                "reference_price": None,
                "reference_kind": None,
            }
        current_notional = _to_decimal(account.current_notional_usd)
        if current_notional <= 0:
            return {
                "drawdown_pct": 0.0,
                "reference_price": None,
                "reference_kind": None,
            }
        entry = _to_decimal(account.entry_price)
        mark = _to_decimal(snapshot_mark)
        references = dict(risk_state.get("position_references_by_coin") or {})
        previous = dict(references.get(coin) or {})
        previous_side = str(previous.get("side") or "").lower()
        previous_reference = _to_decimal(previous.get("reference_price"))
        if previous_side != side or previous_reference <= 0:
            previous_reference = entry
        if side == "short":
            reference = min(previous_reference, mark)
            drawdown_pct = max(0.0, float((mark - reference) / reference * Decimal("100"))) if reference > 0 else 0.0
            reference_kind = "trough"
        else:
            reference = max(previous_reference, mark)
            drawdown_pct = max(0.0, float((reference - mark) / reference * Decimal("100"))) if reference > 0 else 0.0
            reference_kind = "peak"
        return {
            "drawdown_pct": round(drawdown_pct, 4),
            "reference_price": str(reference),
            "reference_kind": reference_kind,
        }

    @staticmethod
    def _position_lock_mode(*, coin: str, risk_state: dict[str, Any]) -> str | None:
        payload = dict(dict(risk_state.get("position_locks") or {}).get(coin) or {})
        return str(payload.get("mode") or "") or None

    @staticmethod
    def _position_lock_strategy_key(*, coin: str, risk_state: dict[str, Any]) -> str | None:
        payload = dict(dict(risk_state.get("position_locks") or {}).get(coin) or {})
        return str(payload.get("strategy_key") or "") or None

    @staticmethod
    def _combine_lock_modes(*, portfolio_mode: str | None, position_mode: str | None) -> str | None:
        modes = [mode for mode in (portfolio_mode, position_mode) if mode]
        if not modes:
            return None
        return max(modes, key=lambda value: _LOCK_PRECEDENCE.get(value, 0))

    @staticmethod
    def _lock_violation_reason(*, lock_mode: str | None, action: str) -> str | None:
        if lock_mode == "flat_only" and action not in _FLAT_ALLOWED_ACTIONS:
            return "portfolio_lock_flat_only"
        if lock_mode == "reduce_only" and action not in _REDUCE_ALLOWED_ACTIONS:
            return "portfolio_lock_reduce_only"
        return None

    @staticmethod
    def _is_risk_reducing_action(action: str) -> bool:
        return action in _RISK_REDUCING_ACTIONS

    @staticmethod
    def _strategy_key(payload: dict[str, Any] | None) -> str:
        data = dict(payload or {})
        strategy_id = str(data.get("strategy_id") or "").strip()
        revision = str(data.get("revision_number") or "").strip()
        if strategy_id or revision:
            return f"{strategy_id}:{revision}"
        return ""

    @staticmethod
    def _effective_execution_leverage(*, requested: str | None, max_allowed: float) -> str:
        try:
            requested_value = float(requested) if requested is not None else max_allowed
        except (TypeError, ValueError):
            requested_value = max_allowed
        return str(min(requested_value, max_allowed))


def _to_decimal(raw: Any) -> Decimal:
    try:
        return Decimal(str(raw or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")
