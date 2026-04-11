from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from threading import Event, Thread
from typing import Any

from ...shared.infra import EventBus
from ...shared.protocols import EventFactory
from ...shared.utils import new_id, notional_to_pct_of_exposure_budget
from ..policy_risk.models import GuardDecision
from ..policy_risk.service import PolicyRiskService
from ..memory_assets.service import MemoryAssetsService
from ..trade_gateway.execution.models import ExecutionDecision
from ..trade_gateway.execution.service import ExecutionGatewayService
from ..trade_gateway.market_data.models import DataIngestBundle
from ..trade_gateway.market_data.service import DataIngestService
from .events import EVENT_RISK_BRAKE_TRIGGERED, MODULE_NAME
from .pm_trigger import record_pm_trigger_event
from .rt_trigger import DEFAULT_RT_JOB_ID, CronRunResult, OpenClawCronRunner


DEFAULT_PM_JOB_ID = "d4153cc9-1cbf-431d-b45a-d822054672c5"

_STATE_RANK = {"normal": 0, "observe": 1, "reduce": 2, "exit": 3, "breaker": 4}


@dataclass(frozen=True)
class RiskBrakeConfig:
    enabled: bool = False
    scan_interval_seconds: int = 30
    rt_job_id: str = DEFAULT_RT_JOB_ID
    pm_job_id: str = DEFAULT_PM_JOB_ID
    cron_subprocess_timeout_seconds: int = 15
    openclaw_bin: str = "openclaw"


class RiskBrakeMonitor:
    def __init__(
        self,
        *,
        memory_assets: MemoryAssetsService,
        market_data: DataIngestService,
        policy_risk: PolicyRiskService,
        trade_execution: ExecutionGatewayService,
        event_bus: EventBus | None = None,
        config: RiskBrakeConfig | None = None,
        cron_runner: OpenClawCronRunner | None = None,
    ) -> None:
        self.memory_assets = memory_assets
        self.market_data = market_data
        self.policy_risk = policy_risk
        self.trade_execution = trade_execution
        self.event_bus = event_bus
        self.config = config or RiskBrakeConfig()
        self.cron_runner = cron_runner or OpenClawCronRunner(
            openclaw_bin=self.config.openclaw_bin,
            timeout_seconds=self.config.cron_subprocess_timeout_seconds,
        )
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if not self.config.enabled or self._thread is not None:
            return
        self._thread = Thread(target=self._loop, name="workflow-orchestrator-risk-brake", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def scan_once(self, *, now: datetime | None = None) -> dict[str, Any]:
        current = _as_utc(now or datetime.now(UTC))
        trace_id = new_id("trace")
        state = self._normalize_state(self._load_state(), now=current)
        latest_strategy_asset = self.memory_assets.get_latest_strategy()
        strategy_payload = dict((latest_strategy_asset or {}).get("payload") or {})
        current_strategy_key = self._strategy_key(strategy_payload)
        state = self._release_locks_for_strategy(state=state, current_strategy_key=current_strategy_key, now=current)
        market = self.market_data.get_market_overview(trace_id=trace_id)
        policies = self.policy_risk.evaluate(
            market=market,
            forecasts={},
            news_events=[],
            prior_risk_state=state,
            latest_strategy=strategy_payload,
            current_time=current,
        )
        event_payload = self._handle_risk_event(
            state=state,
            market=market,
            policies=policies,
            strategy_payload=strategy_payload,
            current_strategy_key=current_strategy_key,
            now=current,
            trace_id=trace_id,
        )
        updated_state = self._updated_state_after_scan(
            state=state,
            market=market,
            policies=policies,
            current_strategy_key=current_strategy_key,
            now=current,
            event_payload=event_payload,
        )
        self._save_state(updated_state, trace_id=trace_id)
        return event_payload or {"triggered": False, "scanned_at_utc": current.isoformat()}

    def _loop(self) -> None:
        while not self._stop.wait(max(int(self.config.scan_interval_seconds), 1)):
            try:
                self.scan_once()
            except Exception:
                continue

    def _handle_risk_event(
        self,
        *,
        state: dict[str, Any],
        market: DataIngestBundle,
        policies: dict[str, GuardDecision],
        strategy_payload: dict[str, Any],
        current_strategy_key: str,
        now: datetime,
        trace_id: str,
    ) -> dict[str, Any] | None:
        plan = self._plan_actions(
            state=state,
            market=market,
            policies=policies,
            current_strategy_key=current_strategy_key,
        )
        if plan is None:
            return None

        event_id = new_id("risk_brake")
        payload: dict[str, Any] = {
            "event_id": event_id,
            "detected_at_utc": now.isoformat(),
            "scope": plan["scope"],
            "state": plan["state"],
            "coins": sorted(plan["actions"].keys()),
            "risk_lock_updates": plan["risk_lock_updates"],
            "portfolio_risk_state": plan["portfolio_risk_state"],
            "position_risk_state_by_coin": plan["position_risk_state_by_coin"],
            "strategy_key": current_strategy_key,
            "system_decision_id": None,
            "execution_result_ids": [],
            "rt_dispatched": False,
            "rt_skip_reason": None,
            "pm_dispatched": False,
            "pm_skip_reason": None,
        }

        if plan["state"] in {"reduce", "exit"} and plan["actions"]:
            batch_summary = self._execute_system_orders(
                trace_id=trace_id,
                event_id=event_id,
                market=market,
                policies=policies,
                actions=plan["actions"],
                strategy_payload=strategy_payload,
                reason_label=plan["reason_label"],
            )
            payload.update(batch_summary)
            dispatch_summary = self._dispatch_rt_and_pm(
                trace_id=trace_id,
                now=now,
                reason=plan["reason_label"],
                strategy_key=current_strategy_key,
                scope=plan["scope"],
                state_name=plan["state"],
                coins=sorted(plan["actions"].keys()),
            )
            payload.update(dispatch_summary)
        self.memory_assets.save_asset(
            asset_type="risk_brake_event",
            asset_id=event_id,
            payload=payload,
            trace_id=trace_id,
            actor_role="system",
            group_key=plan["reason_label"],
            metadata={"scope": plan["scope"], "state": plan["state"]},
        )
        envelope = EventFactory.build(
            trace_id=trace_id,
            event_type=EVENT_RISK_BRAKE_TRIGGERED,
            source_module=MODULE_NAME,
            entity_type="risk_brake_event",
            entity_id=event_id,
            payload=payload,
        )
        self.memory_assets.append_event(envelope)
        self._publish_best_effort(envelope)
        payload["triggered"] = True
        return payload

    def _plan_actions(
        self,
        *,
        state: dict[str, Any],
        market: DataIngestBundle,
        policies: dict[str, GuardDecision],
        current_strategy_key: str,
    ) -> dict[str, Any] | None:
        previous_portfolio_state = str(state.get("last_portfolio_state") or "normal")
        current_portfolio_state = self._portfolio_state(policies)
        previous_position_states = {
            str(coin).upper(): str(value)
            for coin, value in dict(state.get("last_position_state_by_coin") or {}).items()
        }
        current_position_states = {
            coin: policy.position_risk_state.state
            for coin, policy in policies.items()
        }

        action_map: dict[str, dict[str, Any]] = {}
        risk_lock_updates = {
            "portfolio_lock": {},
            "position_locks": {},
        }
        scope = "none"
        state_name = "normal"
        reason_label = ""

        if self._is_rising(previous_portfolio_state, current_portfolio_state, "exit"):
            scope = "portfolio"
            state_name = "exit"
            reason_label = "portfolio_peak_exit"
            for position in market.portfolio.positions:
                action_map[str(position.coin).upper()] = {
                    "action": "close",
                    "reason": "portfolio_peak_exit",
                }
            risk_lock_updates["portfolio_lock"] = {
                "mode": "flat_only",
                "strategy_key": current_strategy_key,
                "triggered_at_utc": datetime.now(UTC).isoformat(),
            }
        else:
            if self._is_rising(previous_portfolio_state, current_portfolio_state, "reduce"):
                scope = "portfolio"
                state_name = "reduce"
                reason_label = "portfolio_peak_reduce"
                for position in market.portfolio.positions:
                    if _to_decimal(position.unrealized_pnl_usd) < 0:
                        action_map[str(position.coin).upper()] = {
                            "action": "reduce",
                            "reason": "portfolio_peak_reduce",
                        }
                if action_map:
                    risk_lock_updates["portfolio_lock"] = {
                        "mode": "reduce_only",
                        "strategy_key": current_strategy_key,
                        "triggered_at_utc": datetime.now(UTC).isoformat(),
                    }
            for coin, current_state in current_position_states.items():
                previous_state = previous_position_states.get(coin, "normal")
                if self._is_rising(previous_state, current_state, "exit"):
                    action_map[coin] = {
                        "action": "close",
                        "reason": "position_peak_exit",
                    }
                    risk_lock_updates["position_locks"][coin] = {
                        "mode": "flat_only",
                        "strategy_key": current_strategy_key,
                        "triggered_at_utc": datetime.now(UTC).isoformat(),
                    }
                    if scope == "none":
                        scope = "position"
                        state_name = "exit"
                        reason_label = "position_peak_exit"
                elif self._is_rising(previous_state, current_state, "reduce") and coin not in action_map:
                    action_map[coin] = {
                        "action": "reduce",
                        "reason": "position_peak_reduce",
                    }
                    risk_lock_updates["position_locks"][coin] = {
                        "mode": "reduce_only",
                        "strategy_key": current_strategy_key,
                        "triggered_at_utc": datetime.now(UTC).isoformat(),
                    }
                    if scope == "none":
                        scope = "position"
                        state_name = "reduce"
                        reason_label = "position_peak_reduce"

        if not action_map:
            return None
        return {
            "scope": scope,
            "state": state_name,
            "reason_label": reason_label,
            "actions": action_map,
            "risk_lock_updates": risk_lock_updates,
            "portfolio_risk_state": next(
                (
                    policy.portfolio_risk_state.model_dump(mode="json")
                    for policy in policies.values()
                ),
                {},
            ),
            "position_risk_state_by_coin": {
                coin: policy.position_risk_state.model_dump(mode="json")
                for coin, policy in policies.items()
                if coin in action_map
            },
        }

    def _execute_system_orders(
        self,
        *,
        trace_id: str,
        event_id: str,
        market: DataIngestBundle,
        policies: dict[str, GuardDecision],
        actions: dict[str, dict[str, Any]],
        strategy_payload: dict[str, Any],
        reason_label: str,
    ) -> dict[str, Any]:
        strategy_id = str(strategy_payload.get("strategy_id") or "risk_brake")
        decision_id = f"{'risk_exit' if 'exit' in reason_label else 'risk_reduce'}_{new_id('decision')}"
        decisions: list[ExecutionDecision] = []
        batch_payload_decisions: list[dict[str, Any]] = []
        portfolio_positions = {
            str(position.coin).upper(): position
            for position in market.portfolio.positions
        }
        for coin, action_payload in actions.items():
            account = market.accounts.get(coin)
            snapshot = market.market.get(coin)
            position = portfolio_positions.get(coin)
            if account is None or snapshot is None or position is None:
                continue
            current_notional = _to_decimal(account.current_notional_usd)
            if current_notional <= 0:
                continue
            action = str(action_payload.get("action") or "reduce")
            if action == "reduce":
                target_notional = current_notional / Decimal("2")
                size_pct = float(position.position_share_pct_of_exposure_budget) / 2.0
            else:
                target_notional = current_notional
                size_pct = float(position.position_share_pct_of_exposure_budget)
            decisions.append(
                ExecutionDecision(
                    decision_id=decision_id,
                    context_id=f"risk-brake:{coin}",
                    strategy_version=strategy_id,
                    product_id=snapshot.product_id,
                    coin=coin,
                    action=action,
                    side=str(account.current_side or position.side or "long"),
                    size_pct_of_exposure_budget=round(size_pct, 4),
                    notional_usd=str(target_notional),
                    leverage=str(account.current_leverage or policies[coin].risk_limits.max_leverage),
                    reason=str(action_payload.get("reason") or reason_label),
                    priority=1,
                    urgency="high",
                    valid_for_minutes=5,
                )
            )
            batch_payload_decisions.append(
                {
                    "symbol": coin,
                    "action": action,
                    "direction": str(account.current_side or position.side or "long"),
                    "reason": str(action_payload.get("reason") or reason_label),
                    "size_pct_of_exposure_budget": round(size_pct, 4),
                    "priority": 1,
                    "urgency": "high",
                    "valid_for_minutes": 5,
                }
            )
        if not decisions:
            return {
                "system_decision_id": decision_id,
                "execution_result_ids": [],
            }

        self.memory_assets.save_asset(
            asset_type="execution_batch",
            payload={
                "decision_id": decision_id,
                "strategy_id": strategy_id,
                "generated_at_utc": datetime.now(UTC).isoformat(),
                "trigger_type": "risk_brake",
                "decisions": batch_payload_decisions,
            },
            trace_id=trace_id,
            actor_role="system",
            group_key=decision_id,
            metadata={"risk_brake_event_id": event_id, "reason": reason_label},
        )
        authorization = self.policy_risk.authorize_execution(
            strategy_payload=strategy_payload,
            decisions=decisions,
            market=market,
            policies=policies,
        )
        self.memory_assets.save_asset(
            asset_type="execution_authorization",
            payload=authorization.model_dump(mode="json"),
            trace_id=trace_id,
            actor_role="policy_risk",
            group_key=decision_id,
            metadata={"risk_brake_event_id": event_id, "reason": reason_label},
        )
        self._record_events(
            self.policy_risk.build_execution_authorization_events(
                trace_id=trace_id,
                authorization=authorization,
            )
        )
        accepted = [ExecutionDecision.model_validate(item) for item in authorization.accepted]
        plans = self.trade_execution.build_execution_plans(
            decisions=accepted,
            total_equity_usd=market.portfolio.total_equity_usd,
            max_leverage=next(
                (
                    policy.risk_limits.max_leverage
                    for policy in policies.values()
                    if policy.risk_limits.max_leverage
                ),
                1.0,
            ),
        )
        self._record_events(self.trade_execution.build_plan_events(trace_id=trace_id, plans=plans))
        results = self.trade_execution.execute(plans, live=True)
        self._record_events(self.trade_execution.build_result_events(trace_id=trace_id, results=results))
        result_asset_ids: list[str] = []
        for result in results:
            asset = self.memory_assets.save_asset(
                asset_type="execution_result",
                payload={"result_id": new_id("execution_result"), **result.model_dump(mode="json")},
                trace_id=trace_id,
                actor_role="system",
                group_key=decision_id,
                metadata={"risk_brake_event_id": event_id, "reason": reason_label, "live": True},
            )
            result_asset_ids.append(str(asset["asset_id"]))
        return {
            "system_decision_id": decision_id,
            "execution_result_ids": result_asset_ids,
        }

    def _dispatch_rt_and_pm(
        self,
        *,
        trace_id: str,
        now: datetime,
        reason: str,
        strategy_key: str,
        scope: str,
        state_name: str,
        coins: list[str],
    ) -> dict[str, Any]:
        rt_running = self.cron_runner.is_running(job_id=self.config.rt_job_id)
        pm_running = self.cron_runner.is_running(job_id=self.config.pm_job_id)
        rt_result: CronRunResult | None = None
        pm_result: CronRunResult | None = None
        rt_skip_reason: str | None = None
        pm_skip_reason: str | None = None
        rt_dispatched = False
        pm_dispatched = False
        if rt_running:
            rt_skip_reason = "cron_running"
        else:
            rt_result = self.cron_runner.run_now(job_id=self.config.rt_job_id)
            rt_dispatched = bool(rt_result.ok)
            if not rt_dispatched:
                rt_skip_reason = "cron_run_failed"
            else:
                self._record_rt_dispatch(now=now, trace_id=trace_id, reason=reason)
        if pm_running:
            pm_skip_reason = "cron_running"
        else:
            pm_result = self.cron_runner.run_now(job_id=self.config.pm_job_id)
            pm_dispatched = bool(pm_result.ok)
            if not pm_dispatched:
                pm_skip_reason = "cron_run_failed"
        pm_event = record_pm_trigger_event(
            memory_assets=self.memory_assets,
            event_bus=self.event_bus,
            trace_id=trace_id,
            payload={
                "event_id": new_id("pm_trigger"),
                "detected_at_utc": now.isoformat(),
                "trigger_type": "risk_brake",
                "trigger_category": "workflow",
                "reason": reason,
                "severity": "high",
                "wake_source": "workflow_orchestrator",
                "claimable": bool(pm_dispatched or pm_running),
                "strategy_key": strategy_key,
                "scope": scope,
                "state": state_name,
                "coins": list(coins),
                "lock_mode": "flat_only" if state_name == "exit" else "reduce_only",
                "dispatched": pm_dispatched,
                "skipped_reason": pm_skip_reason,
                "cron_running": pm_running,
                "pm_cron_stdout": _truncate(pm_result.stdout if pm_result else "", 800),
                "pm_cron_stderr": _truncate(pm_result.stderr if pm_result else "", 800),
            },
            metadata={"trigger_type": "risk_brake", "reason": reason},
        )
        return {
            "rt_dispatched": rt_dispatched,
            "rt_skip_reason": rt_skip_reason,
            "rt_cron_stdout": _truncate(rt_result.stdout if rt_result else "", 800),
            "rt_cron_stderr": _truncate(rt_result.stderr if rt_result else "", 800),
            "pm_trigger_event_id": pm_event["event_id"],
            "pm_dispatched": pm_dispatched,
            "pm_skip_reason": pm_skip_reason,
            "pm_cron_stdout": _truncate(pm_result.stdout if pm_result else "", 800),
            "pm_cron_stderr": _truncate(pm_result.stderr if pm_result else "", 800),
        }

    def _record_rt_dispatch(self, *, now: datetime, trace_id: str, reason: str) -> None:
        asset = self.memory_assets.get_asset("rt_trigger_state")
        payload = dict((asset or {}).get("payload") or {})
        recent = [
            item
            for item in list(payload.get("recent_trigger_times_utc") or [])
            if (parsed := _parse_datetime(item)) is not None and parsed >= now.replace(minute=0, second=0, microsecond=0)
        ]
        recent.append(now.isoformat())
        by_key = dict(payload.get("last_trigger_by_key") or {})
        by_key[f"risk_brake:{reason}"] = now.isoformat()
        payload.update(
            {
                "last_trigger_at_utc": now.isoformat(),
                "recent_trigger_times_utc": recent[-12:],
                "last_trigger_by_key": by_key,
            }
        )
        self.memory_assets.save_asset(
            asset_type="rt_trigger_state",
            asset_id="rt_trigger_state",
            payload=payload,
            trace_id=trace_id,
            actor_role="system",
            group_key="risk_trader",
        )

    def _updated_state_after_scan(
        self,
        *,
        state: dict[str, Any],
        market: DataIngestBundle,
        policies: dict[str, GuardDecision],
        current_strategy_key: str,
        now: datetime,
        event_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        updated = dict(state)
        updated["last_scan_at_utc"] = now.isoformat()
        updated["last_seen_strategy_key"] = current_strategy_key
        updated["portfolio_day_utc"] = now.date().isoformat()
        current_equity = float(market.portfolio.total_equity_usd or 0.0)
        previous_peak = float(updated.get("portfolio_day_peak_equity_usd") or 0.0)
        updated["portfolio_day_peak_equity_usd"] = str(max(previous_peak, current_equity))
        updated["position_references_by_coin"] = self._position_references_snapshot(
            market=market,
            policies=policies,
        )
        updated["last_portfolio_state"] = self._portfolio_state(policies)
        updated["last_position_state_by_coin"] = {
            coin: policy.position_risk_state.state
            for coin, policy in policies.items()
        }
        if event_payload is not None:
            risk_lock_updates = dict(event_payload.get("risk_lock_updates") or {})
            portfolio_lock = dict(risk_lock_updates.get("portfolio_lock") or {})
            if portfolio_lock:
                updated["portfolio_lock"] = portfolio_lock
            position_locks = dict(updated.get("position_locks") or {})
            for coin, payload in dict(risk_lock_updates.get("position_locks") or {}).items():
                position_locks[str(coin).upper()] = dict(payload or {})
            updated["position_locks"] = position_locks
            updated["last_risk_brake_event_id"] = event_payload.get("event_id")
        updated = self._release_locks_for_strategy(
            state=updated,
            current_strategy_key=current_strategy_key,
            now=now,
        )
        return updated

    def _position_references_snapshot(
        self,
        *,
        market: DataIngestBundle,
        policies: dict[str, GuardDecision],
    ) -> dict[str, dict[str, Any]]:
        references: dict[str, dict[str, Any]] = {}
        for coin, account in market.accounts.items():
            if account.current_side is None or _to_decimal(account.current_notional_usd) <= 0:
                continue
            policy = policies.get(coin)
            if policy is None or not policy.position_risk_state.reference_price:
                continue
            references[coin] = {
                "side": account.current_side,
                "reference_price": policy.position_risk_state.reference_price,
                "reference_kind": policy.position_risk_state.reference_kind,
                "captured_at_utc": datetime.now(UTC).isoformat(),
            }
        return references

    def _load_state(self) -> dict[str, Any]:
        asset = self.memory_assets.get_asset("risk_brake_state")
        if asset is None:
            return {}
        payload = asset.get("payload")
        return dict(payload or {}) if isinstance(payload, dict) else {}

    def _save_state(self, payload: dict[str, Any], *, trace_id: str) -> None:
        self.memory_assets.save_asset(
            asset_type="risk_brake_state",
            asset_id="risk_brake_state",
            payload=payload,
            trace_id=trace_id,
            actor_role="system",
            group_key="policy_risk",
        )

    @staticmethod
    def _portfolio_state(policies: dict[str, GuardDecision]) -> str:
        for policy in policies.values():
            return policy.portfolio_risk_state.state
        return "normal"

    @staticmethod
    def _is_rising(previous_state: str, current_state: str, target_state: str) -> bool:
        return (
            _STATE_RANK.get(current_state, 0) >= _STATE_RANK.get(target_state, 0)
            and _STATE_RANK.get(previous_state, 0) < _STATE_RANK.get(target_state, 0)
        )

    @staticmethod
    def _strategy_key(payload: dict[str, Any]) -> str:
        strategy_id = str(payload.get("strategy_id") or "").strip()
        revision = str(payload.get("revision_number") or "").strip()
        if strategy_id or revision:
            return f"{strategy_id}:{revision}"
        return ""

    @staticmethod
    def _normalize_state(state: dict[str, Any], *, now: datetime) -> dict[str, Any]:
        normalized = dict(state or {})
        if str(normalized.get("portfolio_day_utc") or "") != now.date().isoformat():
            normalized["portfolio_day_utc"] = now.date().isoformat()
            normalized["portfolio_day_peak_equity_usd"] = "0"
            normalized["last_portfolio_state"] = "normal"
            normalized["last_position_state_by_coin"] = {}
            normalized["position_references_by_coin"] = {}
        normalized.setdefault("portfolio_lock", {})
        normalized.setdefault("position_locks", {})
        return normalized

    @staticmethod
    def _release_locks_for_strategy(
        *,
        state: dict[str, Any],
        current_strategy_key: str,
        now: datetime,
    ) -> dict[str, Any]:
        updated = dict(state)
        portfolio_lock = dict(updated.get("portfolio_lock") or {})
        if portfolio_lock and current_strategy_key and str(portfolio_lock.get("strategy_key") or "") != current_strategy_key:
            updated["portfolio_lock"] = {}
        position_locks: dict[str, dict[str, Any]] = {}
        for coin, payload in dict(updated.get("position_locks") or {}).items():
            item = dict(payload or {})
            if current_strategy_key and str(item.get("strategy_key") or "") != current_strategy_key:
                continue
            position_locks[str(coin).upper()] = item
        updated["position_locks"] = position_locks
        return updated

    def _record_events(self, events) -> None:
        for event in list(events):
            self.memory_assets.append_event(event)
            self._publish_best_effort(event)

    def _publish_best_effort(self, event) -> None:
        if self.event_bus is None:
            return None
        try:
            self.event_bus.publish(event)
        except Exception:
            return None


def _parse_datetime(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return _as_utc(raw)
    try:
        return _as_utc(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))
    except Exception:
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _to_decimal(raw: Any) -> Decimal:
    try:
        return Decimal(str(raw or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
