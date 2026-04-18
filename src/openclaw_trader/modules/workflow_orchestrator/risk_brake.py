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
from .agent_dispatch import AgentDispatcher, AgentDispatchConfig
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
    pm_session_key: str = "agent:pm:main"
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
        agent_dispatcher: AgentDispatcher | None = None,
    ) -> None:
        self.memory_assets = memory_assets
        self.market_data = market_data
        self.policy_risk = policy_risk
        self.trade_execution = trade_execution
        self.event_bus = event_bus
        self.config = config or RiskBrakeConfig()
        # RT still dispatches via openclaw cron (isolated session) — RT's
        # main-session migration is a separate question. PM, on the other
        # hand, is unified into its main session via agent_dispatcher.
        self.cron_runner = cron_runner or OpenClawCronRunner(
            openclaw_bin=self.config.openclaw_bin,
            timeout_seconds=self.config.cron_subprocess_timeout_seconds,
        )
        self.agent_dispatcher = agent_dispatcher or AgentDispatcher(
            config=AgentDispatchConfig(
                openclaw_bin=self.config.openclaw_bin,
                subprocess_timeout_seconds=self.config.cron_subprocess_timeout_seconds,
            ),
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

        # Dispatch routing — same three-line semantic across scopes:
        #   observe (portfolio OR position) → RT only, no orders
        #   reduce  (portfolio OR position) → auto-cut, then PM only
        #   exit    (portfolio OR position) → auto-close, then PM only
        scope = plan["scope"]
        state_name = plan["state"]
        if state_name == "observe":
            dispatch_rt = True
            dispatch_pm = False
        elif state_name in {"reduce", "exit"}:
            dispatch_rt = False
            dispatch_pm = True
        else:
            # State shouldn't end up here, but if it does (e.g. a future
            # enum member), ping both arms so nothing is silently ignored.
            dispatch_rt = True
            dispatch_pm = True

        if state_name in {"reduce", "exit"} and plan["actions"]:
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

        dispatch_summary = self._dispatch_to_agents(
            trace_id=trace_id,
            now=now,
            reason=plan["reason_label"],
            strategy_key=current_strategy_key,
            scope=scope,
            state_name=state_name,
            coins=sorted(plan["actions"].keys()),
            dispatch_rt=dispatch_rt,
            dispatch_pm=dispatch_pm,
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
        # Compare against the day's worst-so-far state (ladder), not the last
        # scan's instantaneous state. Without this, equity that dips below a
        # line, recovers, then dips again would re-fire and re-dispatch. The
        # ladder only ratchets upward within a day and resets at UTC rollover
        # in `_normalize_state`. Same pattern for portfolio AND per-coin.
        previous_portfolio_state = str(
            state.get("portfolio_state_ladder_high")
            or state.get("last_portfolio_state")
            or "normal"
        )
        current_portfolio_state = self._portfolio_state(policies)
        position_ladder_high = {
            str(coin).upper(): str(value)
            for coin, value in dict(state.get("position_state_ladder_high_by_coin") or {}).items()
        }
        previous_last_position_states = {
            str(coin).upper(): str(value)
            for coin, value in dict(state.get("last_position_state_by_coin") or {}).items()
        }
        current_position_states = {
            coin: policy.position_risk_state.state
            for coin, policy in policies.items()
        }

        def _previous_position(coin: str) -> str:
            # Prefer the sticky ladder; fall back to last_position_state for
            # pre-existing state assets that don't carry the ladder yet.
            return position_ladder_high.get(coin) or previous_last_position_states.get(coin) or "normal"

        # First, pick the highest level rising at portfolio scope.
        portfolio_level: str | None = None
        if self._is_rising(previous_portfolio_state, current_portfolio_state, "exit"):
            portfolio_level = "exit"
        elif self._is_rising(previous_portfolio_state, current_portfolio_state, "reduce"):
            portfolio_level = "reduce"
        elif self._is_rising(previous_portfolio_state, current_portfolio_state, "observe"):
            portfolio_level = "observe"

        # Per-coin highest rising level — independent of portfolio.
        position_rising: dict[str, str] = {}
        for coin, curr in current_position_states.items():
            prev = _previous_position(coin)
            if self._is_rising(prev, curr, "exit"):
                position_rising[coin] = "exit"
            elif self._is_rising(prev, curr, "reduce"):
                position_rising[coin] = "reduce"
            elif self._is_rising(prev, curr, "observe"):
                position_rising[coin] = "observe"

        portfolio_rank = _STATE_RANK.get(portfolio_level or "normal", 0)
        highest_position_rank = (
            max((_STATE_RANK[lvl] for lvl in position_rising.values()), default=0)
        )

        if portfolio_rank == 0 and highest_position_rank == 0:
            return None

        action_map: dict[str, dict[str, Any]] = {}
        risk_lock_updates = {
            "portfolio_lock": {},
            "position_locks": {},
        }
        now_iso = datetime.now(UTC).isoformat()

        # Portfolio trumps position when its rank is ≥ the worst per-coin.
        # Otherwise we fire at position scope (a single coin breached more
        # aggressively than the whole book).
        if portfolio_rank >= highest_position_rank and portfolio_level is not None:
            scope = "portfolio"
            state_name = portfolio_level
            reason_label = f"portfolio_peak_{portfolio_level}"
            if portfolio_level == "exit":
                for position in market.portfolio.positions:
                    action_map[str(position.coin).upper()] = {
                        "action": "close",
                        "reason": reason_label,
                    }
                risk_lock_updates["portfolio_lock"] = {
                    "mode": "flat_only",
                    "strategy_key": current_strategy_key,
                    "triggered_at_utc": now_iso,
                }
            elif portfolio_level == "reduce":
                for position in market.portfolio.positions:
                    if _to_decimal(position.unrealized_pnl_usd) < 0:
                        action_map[str(position.coin).upper()] = {
                            "action": "reduce",
                            "reason": reason_label,
                        }
                if action_map:
                    risk_lock_updates["portfolio_lock"] = {
                        "mode": "reduce_only",
                        "strategy_key": current_strategy_key,
                        "triggered_at_utc": now_iso,
                    }
            # observe: no action, no lock — RT-only notification.
        else:
            scope = "position"
            # state_name = the highest rising level across all affected coins;
            # each coin contributes its own action so a mix of reduce/exit in
            # one scan still closes the exit-ers and halves the reduce-ers.
            highest_level = next(
                lvl for lvl, rank in _STATE_RANK.items() if rank == highest_position_rank
            )
            state_name = highest_level
            reason_label = f"position_peak_{highest_level}"
            for coin, lvl in position_rising.items():
                if lvl == "exit":
                    action_map[coin] = {"action": "close", "reason": f"position_peak_{lvl}"}
                    risk_lock_updates["position_locks"][coin] = {
                        "mode": "flat_only",
                        "strategy_key": current_strategy_key,
                        "triggered_at_utc": now_iso,
                    }
                elif lvl == "reduce":
                    action_map[coin] = {"action": "reduce", "reason": f"position_peak_{lvl}"}
                    risk_lock_updates["position_locks"][coin] = {
                        "mode": "reduce_only",
                        "strategy_key": current_strategy_key,
                        "triggered_at_utc": now_iso,
                    }
                # observe: no action, no lock.
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

    def _dispatch_to_agents(
        self,
        *,
        trace_id: str,
        now: datetime,
        reason: str,
        strategy_key: str,
        scope: str,
        state_name: str,
        coins: list[str],
        dispatch_rt: bool,
        dispatch_pm: bool,
    ) -> dict[str, Any]:
        """Dispatch one or both of RT / PM, depending on the line that just
        tripped. Observe pings only RT; portfolio reduce / exit ping only PM
        (after the system has already auto-executed the order); position-
        level events still ping both arms."""
        rt_running: bool | None = None
        rt_result: CronRunResult | None = None
        rt_skip_reason: str | None = None
        pm_skip_reason: str | None = None
        rt_dispatched = False
        pm_dispatched = False
        pm_dispatch_pid: int | None = None
        pm_dispatch_error: str | None = None

        if dispatch_rt:
            rt_running = self.cron_runner.is_running(job_id=self.config.rt_job_id)
            if rt_running:
                rt_skip_reason = "cron_running"
            else:
                rt_result = self.cron_runner.run_now(job_id=self.config.rt_job_id)
                rt_dispatched = bool(rt_result.ok)
                if not rt_dispatched:
                    rt_skip_reason = "cron_run_failed"
                else:
                    self._record_rt_dispatch(now=now, trace_id=trace_id, reason=reason)
        else:
            rt_skip_reason = "not_required_for_this_line"

        summary: dict[str, Any] = {
            "rt_dispatched": rt_dispatched,
            "rt_skip_reason": rt_skip_reason,
            "rt_cron_stdout": _truncate(rt_result.stdout if rt_result else "", 800),
            "rt_cron_stderr": _truncate(rt_result.stderr if rt_result else "", 800),
            "pm_dispatched": pm_dispatched,
            "pm_skip_reason": None,
        }

        if dispatch_pm:
            # Dispatch into PM main session (not isolated cron). Queueing is
            # acceptable per design: if PM is mid-turn, the risk_brake wake
            # arrives after the current turn completes.
            pm_message = self.agent_dispatcher.fetch_cron_job_payload_message(
                job_id=self.config.pm_job_id
            )
            if not pm_message:
                pm_skip_reason = "missing_pm_payload_message"
            else:
                pm_result = self.agent_dispatcher.send_to_session(
                    agent="pm",
                    session_key=self.config.pm_session_key,
                    message=pm_message,
                )
                pm_dispatched = bool(pm_result.ok)
                pm_dispatch_pid = pm_result.pid
                pm_dispatch_error = pm_result.error
                if not pm_dispatched:
                    pm_skip_reason = f"dispatch_failed:{pm_result.error or 'unknown'}"
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
                    "claimable": bool(pm_dispatched),
                    "strategy_key": strategy_key,
                    "scope": scope,
                    "state": state_name,
                    "coins": list(coins),
                    "lock_mode": "flat_only" if state_name == "exit" else "reduce_only",
                    "dispatched": pm_dispatched,
                    "skipped_reason": pm_skip_reason,
                    "dispatch_target": "agent:pm:main",
                    "dispatch_pid": pm_dispatch_pid,
                    "dispatch_error": pm_dispatch_error,
                },
                metadata={"trigger_type": "risk_brake", "reason": reason},
            )
            summary.update(
                {
                    "pm_trigger_event_id": pm_event["event_id"],
                    "pm_dispatched": pm_dispatched,
                    "pm_skip_reason": pm_skip_reason,
                    "pm_dispatch_pid": pm_dispatch_pid,
                    "pm_dispatch_error": pm_dispatch_error,
                }
            )
        else:
            summary["pm_skip_reason"] = "not_required_for_this_line"

        return summary

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
        current_portfolio_state = self._portfolio_state(policies)
        updated["last_portfolio_state"] = current_portfolio_state
        previous_ladder_high = str(updated.get("portfolio_state_ladder_high") or "normal")
        updated["portfolio_state_ladder_high"] = self._max_rank_state(previous_ladder_high, current_portfolio_state)
        current_position_states = {
            coin: policy.position_risk_state.state
            for coin, policy in policies.items()
        }
        updated["last_position_state_by_coin"] = dict(current_position_states)
        # Per-coin ratchet — same shape as portfolio_state_ladder_high so
        # per-coin oscillation doesn't re-fire the same line either.
        prior_ladder_by_coin = dict(updated.get("position_state_ladder_high_by_coin") or {})
        ladder_by_coin: dict[str, str] = {}
        for coin, current in current_position_states.items():
            prior = str(prior_ladder_by_coin.get(coin) or "normal")
            ladder_by_coin[coin] = self._max_rank_state(prior, current)
        # Preserve ladder entries for coins that didn't report this scan
        # (e.g. a newly flat coin that temporarily disappeared).
        for coin, prior in prior_ladder_by_coin.items():
            ladder_by_coin.setdefault(coin, str(prior or "normal"))
        updated["position_state_ladder_high_by_coin"] = ladder_by_coin
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
    def _max_rank_state(left: str, right: str) -> str:
        return left if _STATE_RANK.get(left, 0) >= _STATE_RANK.get(right, 0) else right

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
            normalized["portfolio_state_ladder_high"] = "normal"
            normalized["last_position_state_by_coin"] = {}
            normalized["position_state_ladder_high_by_coin"] = {}
            normalized["position_references_by_coin"] = {}
        normalized.setdefault("portfolio_lock", {})
        normalized.setdefault("position_locks", {})
        normalized.setdefault("portfolio_state_ladder_high", "normal")
        normalized.setdefault("position_state_ladder_high_by_coin", {})
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
