from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from ...shared.infra.bus import EventBus
from ...shared.protocols import EventFactory
from ...shared.utils import new_id, notional_to_pct_of_exposure_budget
from ..news_events.models import NewsDigestEvent
from ..news_events.service import NewsEventService
from ..notification_service.service import NotificationService
from ..policy_risk.models import GuardDecision
from ..policy_risk.service import PolicyRiskService
from ..quant_intelligence.models import CoinForecast
from ..quant_intelligence.service import QuantIntelligenceService
from ..state_memory.service import StateMemoryService
from ..trade_gateway.execution.service import ExecutionGatewayService
from ..trade_gateway.execution.models import ExecutionDecision
from ..trade_gateway.market_data.models import DataIngestBundle
from ..trade_gateway.market_data.service import DataIngestService
from .events import (
    EVENT_AGENT_SESSION_RESET,
    EVENT_SUBMISSION_REJECTED,
    EVENT_SUBMISSION_VALIDATED,
    MODULE_NAME,
)
from .models import (
    AgentReply,
    AgentRuntimeLease,
    AgentRuntimeInput,
    AgentRuntimePack,
    AgentTask,
    DirectAgentReminder,
    ExecutionSubmission,
    NewsSubmission,
    RetroLearningAck,
    RetroMeetingResult,
    RetroMeetingTurn,
    RetroTranscriptEntry,
    RetroTurnReply,
    StrategySubmission,
    ValidatedSubmissionEnvelope,
)
from .ports import AgentRunner
from .ports import AgentSessionController
from .ports import TriggerContextBridge


class SubmissionValidationError(ValueError):
    def __init__(
        self,
        *,
        schema_ref: str,
        prompt_ref: str,
        errors: list[str],
        error_kind: str = "agent_invalid_submission",
        raw_reply: str | None = None,
        stderr_summary: str | None = None,
    ) -> None:
        super().__init__("submission_validation_failed")
        self.schema_ref = schema_ref
        self.prompt_ref = prompt_ref
        self.errors = errors
        self.error_kind = error_kind
        self.raw_reply = raw_reply
        self.stderr_summary = stderr_summary


class RuntimeInputLeaseError(ValueError):
    def __init__(self, *, reason: str, input_id: str, agent_role: str, detail: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.input_id = input_id
        self.agent_role = agent_role
        self.detail = detail


class AgentGatewayService:
    _STRATEGY_SCHEMA_REF = "specs/modules/agent_gateway/contracts/strategy.schema.json"
    _STRATEGY_PROMPT_REF = "specs/modules/agent_gateway/contracts/strategy.prompt.md"
    _EXECUTION_SCHEMA_REF = "specs/modules/agent_gateway/contracts/execution.schema.json"
    _EXECUTION_PROMPT_REF = "specs/modules/agent_gateway/contracts/execution.prompt.md"
    _NEWS_SCHEMA_REF = "specs/modules/agent_gateway/contracts/news.schema.json"
    _NEWS_PROMPT_REF = "specs/modules/agent_gateway/contracts/news.prompt.md"
    _CHIEF_RETRO_SPEC_REF = "specs/agents/crypto_chief/spec.md"
    _CHIEF_RETRO_PROMPT_REF = "skills/chief-retro-and-summary/SKILL.md"

    def __init__(
        self,
        *,
        pm_runner: AgentRunner,
        risk_runner: AgentRunner,
        macro_runner: AgentRunner,
        chief_runner: AgentRunner,
        session_controller: AgentSessionController | None = None,
        agent_name_by_role: dict[str, str] | None = None,
        learning_path_by_role: dict[str, str] | None = None,
        state_memory: StateMemoryService | None = None,
        market_data: DataIngestService | None = None,
        news_events: NewsEventService | None = None,
        quant_intelligence: QuantIntelligenceService | None = None,
        policy_risk: PolicyRiskService | None = None,
        trade_execution: ExecutionGatewayService | None = None,
        notification_service: NotificationService | None = None,
        trigger_bridge: TriggerContextBridge | None = None,
        event_bus: EventBus | None = None,
        runtime_pack_ttl_seconds: int = 900,
        runtime_dispatcher: Any | None = None,
    ) -> None:
        self.pm_runner = pm_runner
        self.risk_runner = risk_runner
        self.macro_runner = macro_runner
        self.chief_runner = chief_runner
        self.session_controller = session_controller
        self.agent_name_by_role = dict(agent_name_by_role or self._DEFAULT_AGENT_NAME_BY_ROLE)
        self.learning_path_by_role = dict(learning_path_by_role or self._DEFAULT_LEARNING_PATH_BY_ROLE)
        self.state_memory = state_memory
        self.market_data = market_data
        self.news_events = news_events
        self.quant_intelligence = quant_intelligence
        self.policy_risk = policy_risk
        self.trade_execution = trade_execution
        self.notification_service = notification_service
        self.trigger_bridge = trigger_bridge
        self.event_bus = event_bus
        self.runtime_pack_ttl_seconds = runtime_pack_ttl_seconds
        self.runtime_dispatcher = runtime_dispatcher

    def bind_runtime_dispatcher(self, runtime_dispatcher: Any) -> None:
        self.runtime_dispatcher = runtime_dispatcher

    def session_id_for_role(self, agent_role: str) -> str:
        session_id = self._resolve_openclaw_main_session_id(agent_role)
        if session_id:
            return session_id
        return self._SESSION_ID_BY_ROLE.get(agent_role, f"{agent_role}-session")

    def pull_pm_runtime_input(
        self,
        *,
        trigger_type: str = "daily_main",
        params: dict[str, object] | None = None,
    ) -> AgentRuntimePack:
        return self._issue_runtime_pack(agent_role="pm", task_kind="strategy", trigger_type=trigger_type, params=params)

    def pull_rt_runtime_input(
        self,
        *,
        trigger_type: str = "cadence",
        params: dict[str, object] | None = None,
    ) -> AgentRuntimePack:
        return self._issue_runtime_pack(agent_role="risk_trader", task_kind="execution", trigger_type=trigger_type, params=params)

    def pull_mea_runtime_input(
        self,
        *,
        trigger_type: str = "cadence",
        params: dict[str, object] | None = None,
    ) -> AgentRuntimePack:
        return self._issue_runtime_pack(
            agent_role="macro_event_analyst",
            task_kind="event_summary",
            trigger_type=trigger_type,
            params=params,
        )

    def pull_chief_retro_pack(
        self,
        *,
        trigger_type: str = "daily_retro",
        params: dict[str, object] | None = None,
    ) -> AgentRuntimePack:
        return self._issue_runtime_pack(agent_role="crypto_chief", task_kind="retro", trigger_type=trigger_type, params=params)

    def submit_strategy(
        self,
        *,
        input_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        lease = self._validate_runtime_lease(input_id=input_id, agent_role="pm")
        envelope = self.validate_submission(
            submission_kind="strategy",
            agent_role="pm",
            trace_id=lease.pack.trace_id,
            payload=payload,
        )
        strategy_payload = self.state_memory.materialize_strategy_asset(
            trace_id=lease.pack.trace_id,
            authored_payload=envelope.payload,
            trigger_type=lease.pack.trigger_type,
            actor_role="pm",
            source_ref=envelope.envelope_id,
        )
        self._record_events(
            [
                self.build_submission_event(trace_id=lease.pack.trace_id, envelope=envelope),
                EventFactory.build(
                    trace_id=lease.pack.trace_id,
                    event_type="strategy.submitted",
                    source_module="agent_gateway",
                    entity_type="strategy",
                    entity_id=str(strategy_payload.get("strategy_id")),
                    payload={
                        "strategy": strategy_payload,
                        "envelope_id": envelope.envelope_id,
                        "trigger_type": lease.pack.trigger_type,
                        "input_id": input_id,
                    },
                ),
            ]
        )
        self.state_memory.save_agent_session(
            agent_role="pm",
            session_id=self.session_id_for_role("pm"),
            last_task_kind="strategy",
            last_submission_kind="strategy",
        )
        self._consume_runtime_lease(lease=lease, submission_kind="strategy")
        if self.trigger_bridge is not None:
            self.trigger_bridge.record_recheck_state(
                trace_id=lease.pack.trace_id,
                strategy_id=str(strategy_payload.get("strategy_id")),
                rechecks=list(strategy_payload.get("scheduled_rechecks") or []),
            )
        return {
            "trace_id": lease.pack.trace_id,
            "input_id": input_id,
            "envelope": envelope.model_dump(mode="json"),
            "strategy": strategy_payload,
        }

    def submit_execution(
        self,
        *,
        input_id: str,
        payload: dict[str, Any],
        live: bool = False,
        max_notional_usd: float | None = None,
    ) -> dict[str, Any]:
        lease = self._validate_runtime_lease(input_id=input_id, agent_role="risk_trader")
        envelope = self.validate_submission(
            submission_kind="execution",
            agent_role="risk_trader",
            trace_id=lease.pack.trace_id,
            payload=payload,
        )
        submission = ExecutionSubmission.model_validate(envelope.payload)
        self._record_events(
            [
                self.build_submission_event(trace_id=lease.pack.trace_id, envelope=envelope),
                EventFactory.build(
                    trace_id=lease.pack.trace_id,
                    event_type="execution.submitted",
                    source_module="agent_gateway",
                    entity_type="execution_batch",
                    entity_id=submission.decision_id,
                    payload={
                        "execution": submission.model_dump(mode="json"),
                        "envelope_id": envelope.envelope_id,
                        "input_id": input_id,
                    },
                ),
            ]
        )
        self.state_memory.save_agent_session(
            agent_role="risk_trader",
            session_id=self.session_id_for_role("risk_trader"),
            last_task_kind="execution",
            last_submission_kind="execution",
        )
        self.state_memory.save_asset(
            asset_type="execution_batch",
            payload=submission.model_dump(mode="json"),
            trace_id=lease.pack.trace_id,
            actor_role="risk_trader",
            group_key=submission.decision_id,
            source_ref=envelope.envelope_id,
            metadata={"strategy_id": submission.strategy_id, "input_id": input_id},
        )

        market = DataIngestBundle.model_validate(lease.hidden_payload.get("market") or {})
        policies = {
            coin: GuardDecision.model_validate(item)
            for coin, item in dict(lease.hidden_payload.get("policies") or {}).items()
        }
        strategy_payload = dict(lease.hidden_payload.get("latest_strategy") or lease.pack.payload.get("strategy") or {})
        context_by_symbol = {
            str(item.get("coin") or "").upper(): item
            for item in list(lease.pack.payload.get("execution_contexts") or [])
            if isinstance(item, dict)
        }
        decisions: list[ExecutionDecision] = []
        for item in submission.decisions:
            runtime_context = context_by_symbol.get(item.symbol, {})
            decisions.append(
                ExecutionDecision(
                    decision_id=submission.decision_id,
                    strategy_version=submission.strategy_id or "unknown",
                    context_id=str(runtime_context.get("context_id") or new_id("execctx")),
                    product_id=str(runtime_context.get("product_id") or f"{item.symbol}-PERP-INTX"),
                    coin=item.symbol,
                    action=item.action,
                    side=item.direction or ("flat" if item.action in {"wait", "hold"} else "long"),
                    size_pct_of_equity=item.size_pct_of_equity,
                    urgency=item.urgency,
                    valid_for_minutes=item.valid_for_minutes,
                    reason=item.reason,
                    priority=item.priority,
                    escalate_to_pm=item.escalate_to_pm,
                    escalation_reason=item.escalation_reason,
                )
            )

        authorization = self.policy_risk.authorize_execution(
            strategy_payload=strategy_payload,
            decisions=decisions,
            market=market,
            policies=policies,
        )
        self._record_events(
            self.policy_risk.build_execution_authorization_events(
                trace_id=lease.pack.trace_id,
                authorization=authorization,
            )
        )
        self.state_memory.save_asset(
            asset_type="execution_authorization",
            payload=authorization.model_dump(mode="json"),
            trace_id=lease.pack.trace_id,
            actor_role="policy_risk",
            group_key=submission.decision_id,
            metadata={"strategy_id": submission.strategy_id, "input_id": input_id},
        )

        accepted = [ExecutionDecision.model_validate(item) for item in authorization.accepted]
        bounded_max_notional = float(max_notional_usd) if live and max_notional_usd is not None else None
        plans = self.trade_execution.build_execution_plans(
            decisions=accepted,
            total_equity_usd=market.portfolio.total_equity_usd,
            max_leverage=next(
                (
                    item.risk_limits.max_leverage
                    for item in policies.values()
                    if item.risk_limits.max_leverage
                ),
                1.0,
            ),
            max_notional_usd=bounded_max_notional,
        )
        self._record_events(self.trade_execution.build_plan_events(trace_id=lease.pack.trace_id, plans=plans))
        results = self.trade_execution.execute(plans, live=live)
        self._record_events(self.trade_execution.build_result_events(trace_id=lease.pack.trace_id, results=results))
        for result in results:
            self.state_memory.save_asset(
                asset_type="execution_result",
                payload={"result_id": new_id("execution_result"), **result.model_dump(mode="json")},
                trace_id=lease.pack.trace_id,
                actor_role="risk_trader",
                group_key=submission.decision_id,
                metadata={"live": live, "input_id": input_id},
            )
        self._consume_runtime_lease(lease=lease, submission_kind="execution")
        return {
            "trace_id": lease.pack.trace_id,
            "input_id": input_id,
            "decision_id": submission.decision_id,
            "strategy_id": submission.strategy_id,
            "accepted_count": len(authorization.accepted),
            "rejected": authorization.rejected,
            "plan_count": len(plans),
            "execution_results": [item.model_dump(mode="json") for item in results],
            "live": bool(live),
        }

    def submit_news(
        self,
        *,
        input_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        lease = self._validate_runtime_lease(input_id=input_id, agent_role="macro_event_analyst")
        envelope = self.validate_submission(
            submission_kind="news",
            agent_role="macro_event_analyst",
            trace_id=lease.pack.trace_id,
            payload=payload,
        )
        submission = NewsSubmission.model_validate(envelope.payload)
        canonical_news = self.state_memory.materialize_news_submission(
            trace_id=lease.pack.trace_id,
            authored_payload=submission.model_dump(mode="json"),
            actor_role="macro_event_analyst",
            source_ref=envelope.envelope_id,
        )
        self._record_events(
            [
                self.build_submission_event(trace_id=lease.pack.trace_id, envelope=envelope),
                EventFactory.build(
                    trace_id=lease.pack.trace_id,
                    event_type="news.submitted",
                    source_module="agent_gateway",
                    entity_type="news_submission",
                    entity_id=str(canonical_news["submission_id"]),
                    payload={
                        "news": canonical_news,
                        "envelope_id": envelope.envelope_id,
                        "input_id": input_id,
                    },
                ),
            ]
        )
        self.state_memory.save_agent_session(
            agent_role="macro_event_analyst",
            session_id=self.session_id_for_role("macro_event_analyst"),
            last_task_kind="event_summary",
            last_submission_kind="news",
        )
        for item in canonical_news["events"]:
            self.state_memory.save_asset(
                asset_type="macro_event",
                payload=item,
                trace_id=lease.pack.trace_id,
                actor_role="macro_event_analyst",
                group_key=str(item["event_id"]),
                source_ref=str(canonical_news["submission_id"]),
            )
        self.state_memory.save_asset(
            asset_type="macro_daily_memory",
            payload={
                "memory_day_utc": new_id("memory_day"),
                "summary": "; ".join(str(event["summary"]) for event in canonical_news["events"][:5]),
                "event_ids": [str(event["event_id"]) for event in canonical_news["events"]],
            },
            trace_id=lease.pack.trace_id,
            actor_role="macro_event_analyst",
            group_key="macro_daily_memory",
            source_ref=envelope.envelope_id,
        )
        reminder_events = []
        for reminder in self._build_direct_reminders_from_news(canonical_news):
            self.state_memory.save_asset(
                asset_type="direct_reminder",
                payload=reminder.model_dump(mode="json"),
                trace_id=lease.pack.trace_id,
                actor_role="macro_event_analyst",
                group_key=reminder.to_agent_role,
                source_ref=str(canonical_news["submission_id"]),
            )
            reminder_events.append(
                EventFactory.build(
                    trace_id=lease.pack.trace_id,
                    event_type="agent.reminder.created",
                    source_module="agent_gateway",
                    entity_type="direct_reminder",
                    entity_id=reminder.reminder_id,
                    payload=reminder.model_dump(mode="json"),
                )
            )
        if reminder_events:
            self._record_events(reminder_events)
        self._consume_runtime_lease(lease=lease, submission_kind="news")
        return {
            "trace_id": lease.pack.trace_id,
            "input_id": input_id,
            "submission_id": canonical_news["submission_id"],
            "macro_event_count": len(canonical_news["events"]),
            "high_impact_count": len([item for item in canonical_news["events"] if item["impact_level"] == "high"]),
        }

    def submit_retro(self, *, input_id: str) -> dict[str, Any]:
        lease = self._validate_runtime_lease(input_id=input_id, agent_role="crypto_chief")
        runtime_inputs = {
            role: AgentRuntimeInput.model_validate(payload)
            for role, payload in dict(lease.hidden_payload.get("runtime_inputs") or {}).items()
        }
        reply_payload = self.run_chief_retro(trace_id=lease.pack.trace_id, runtime_inputs=runtime_inputs)
        owner_summary = str(reply_payload.get("owner_summary") or "").strip()
        reset_command = str(reply_payload.get("reset_command") or "/new")
        transcript = list(reply_payload.get("transcript") or [])
        learning_results = list(reply_payload.get("learning_results") or [])
        learning_completed = bool(reply_payload.get("learning_completed"))
        if owner_summary:
            self._record_events(
                self.notification_service.notify_owner_summary(
                    trace_id=lease.pack.trace_id,
                    owner_summary=owner_summary,
                )
            )
        self._record_events(
            [
                EventFactory.build(
                    trace_id=lease.pack.trace_id,
                    event_type="chief.retro.completed",
                    source_module="agent_gateway",
                    entity_type="chief_summary",
                    entity_id=new_id("retro"),
                    payload={
                        "owner_summary": owner_summary,
                        "reset_command": reset_command,
                        "learning_completed": learning_completed,
                        "round_count": reply_payload.get("round_count"),
                        "transcript": transcript,
                        "learning_results": learning_results,
                        "input_id": input_id,
                    },
                )
            ]
        )
        self._consume_runtime_lease(lease=lease, submission_kind="retro")
        return {
            "trace_id": lease.pack.trace_id,
            "input_id": input_id,
            "owner_summary": owner_summary,
            "reset_command": reset_command,
            "learning_completed": learning_completed,
            "transcript": transcript,
            "learning_results": learning_results,
            "round_count": reply_payload.get("round_count"),
        }

    def _issue_runtime_pack(
        self,
        *,
        agent_role: str,
        task_kind: str,
        trigger_type: str,
        params: dict[str, object] | None = None,
    ) -> AgentRuntimePack:
        self._require_runtime_bridge_dependencies()
        trace_id = new_id("trace")
        trigger_context = self._build_trigger_context(agent_role=agent_role, trigger_type=trigger_type, params=params)
        context = self._collect_bridge_context(agent_role=agent_role, trace_id=trace_id, trigger_type=trigger_type)
        runtime_inputs = self.build_runtime_inputs(
            trace_id=trace_id,
            market=context["market"],
            policies=context["policies"],
            forecasts=context["forecasts"],
            news_events=context["news"],
            latest_strategy=context["latest_strategy"],
            macro_memory=context["macro_memory"],
        )
        runtime_input = runtime_inputs[agent_role]
        expires_at = datetime.now(UTC) + timedelta(seconds=self.runtime_pack_ttl_seconds)
        if agent_role == "crypto_chief":
            payload = {
                "retro_pack": {
                    "market": runtime_inputs["crypto_chief"].payload.get("market", {}),
                    "risk_limits": runtime_inputs["crypto_chief"].payload.get("risk_limits", {}),
                    "forecasts": runtime_inputs["crypto_chief"].payload.get("forecasts", {}),
                    "strategy": runtime_inputs["crypto_chief"].payload.get("previous_strategy", {}),
                    "news_events": runtime_inputs["crypto_chief"].payload.get("news_events", []),
                    "execution_contexts": runtime_inputs["crypto_chief"].payload.get("execution_contexts", []),
                    "macro_memory": runtime_inputs["crypto_chief"].payload.get("macro_memory", []),
                    "recent_execution_results": self.state_memory.get_recent_execution_results(limit=10),
                    "recent_news_submissions": self.state_memory.get_recent_news_submissions(limit=10),
                },
                "trigger_context": trigger_context,
            }
            hidden_payload = {
                "runtime_inputs": {
                    role: item.model_dump(mode="json")
                    for role, item in runtime_inputs.items()
                }
            }
        else:
            payload = dict(runtime_input.payload)
            payload["trigger_context"] = trigger_context
            hidden_payload = {
                "market": context["market"].model_dump(mode="json"),
                "policies": {coin: decision.model_dump(mode="json") for coin, decision in context["policies"].items()},
                "forecasts": {coin: forecast.model_dump(mode="json") for coin, forecast in context["forecasts"].items()},
                "news": [item.model_dump(mode="json") for item in context["news"]],
                "latest_strategy": context["latest_strategy"] or {},
                "macro_memory": list(context["macro_memory"]),
            }
        pack = AgentRuntimePack(
            input_id=runtime_input.input_id,
            trace_id=trace_id,
            agent_role=agent_role,
            task_kind=task_kind,
            trigger_type=trigger_type,
            expires_at_utc=expires_at,
            payload=payload,
        )
        lease = AgentRuntimeLease(
            pack=pack,
            trigger_context=trigger_context,
            hidden_payload=hidden_payload,
        )
        self.state_memory.save_agent_session(
            agent_role=agent_role,
            session_id=self.session_id_for_role(agent_role),
            last_task_kind=task_kind,
        )
        self.state_memory.save_asset(
            asset_type="agent_runtime_lease",
            asset_id=pack.input_id,
            payload=lease.model_dump(mode="json"),
            trace_id=trace_id,
            actor_role="system",
            group_key=agent_role,
            metadata={
                "status": lease.status,
                "trigger_type": trigger_type,
                "expires_at_utc": expires_at.isoformat(),
            },
        )
        if self.trigger_bridge is not None:
            self.trigger_bridge.record_runtime_pack_issued(
                input_id=pack.input_id,
                trace_id=trace_id,
                agent_role=agent_role,
                trigger_context=trigger_context,
                expires_at_utc=expires_at.isoformat(),
            )
        return pack

    def _build_trigger_context(
        self,
        *,
        agent_role: str,
        trigger_type: str,
        params: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if self.trigger_bridge is None:
            return {
                "agent_role": agent_role,
                "trigger_type": trigger_type,
                "requested_at_utc": datetime.now(UTC).isoformat(),
                "metadata": dict(params or {}),
            }
        return self.trigger_bridge.get_trigger_context(
            agent_role=agent_role,
            trigger_type=trigger_type,
            params=params,
        )

    def _collect_bridge_context(
        self,
        *,
        agent_role: str,
        trace_id: str,
        trigger_type: str,
    ) -> dict[str, Any]:
        force_sync_news = agent_role == "macro_event_analyst" and trigger_type == "news_batch_ready"
        market = self.market_data.get_market_overview(trace_id=trace_id)
        self._persist_runtime_bridge_portfolio(
            trace_id=trace_id,
            agent_role=agent_role,
            trigger_type=trigger_type,
            market=market,
        )
        news = self.news_events.get_latest_news_batch(force_sync=force_sync_news)
        forecasts = self.quant_intelligence.get_latest_forecasts(market)
        policies = self.policy_risk.evaluate(market=market, forecasts=forecasts, news_events=news)
        latest_strategy_asset = self.state_memory.get_latest_strategy()
        latest_strategy = latest_strategy_asset["payload"] if latest_strategy_asset and "payload" in latest_strategy_asset else latest_strategy_asset
        macro_memory = self.state_memory.get_macro_memory()
        return {
            "market": market,
            "news": news,
            "forecasts": forecasts,
            "policies": policies,
            "latest_strategy": latest_strategy,
            "macro_memory": macro_memory,
        }

    def _persist_runtime_bridge_portfolio(
        self,
        *,
        trace_id: str,
        agent_role: str,
        trigger_type: str,
        market: DataIngestBundle,
    ) -> None:
        portfolio_payload = market.portfolio.model_dump(mode="json")
        self.state_memory.save_portfolio(trace_id, portfolio_payload)
        self.state_memory.save_asset(
            asset_type="portfolio_snapshot",
            payload=portfolio_payload,
            trace_id=trace_id,
            actor_role="system",
            group_key=trace_id,
            metadata={
                "reason": "runtime_bridge_pull",
                "agent_role": agent_role,
                "trigger_type": trigger_type,
            },
        )

    def _require_runtime_bridge_dependencies(self) -> None:
        missing = [
            name
            for name, value in (
                ("state_memory", self.state_memory),
                ("market_data", self.market_data),
                ("news_events", self.news_events),
                ("quant_intelligence", self.quant_intelligence),
                ("policy_risk", self.policy_risk),
                ("trade_execution", self.trade_execution),
                ("notification_service", self.notification_service),
            )
            if value is None
        ]
        if missing:
            raise RuntimeError(f"agent_runtime_bridge_not_configured:{','.join(missing)}")

    def _validate_runtime_lease(self, *, input_id: str, agent_role: str) -> AgentRuntimeLease:
        self._require_runtime_bridge_dependencies()
        asset = self.state_memory.get_asset(input_id)
        if asset is None or asset.get("asset_type") != "agent_runtime_lease":
            raise RuntimeInputLeaseError(reason="unknown_input_id", input_id=input_id, agent_role=agent_role)
        lease = AgentRuntimeLease.model_validate(asset.get("payload") or {})
        if lease.pack.agent_role != agent_role:
            raise RuntimeInputLeaseError(
                reason="wrong_agent_role",
                input_id=input_id,
                agent_role=agent_role,
                detail=str(lease.pack.agent_role),
            )
        if lease.status == "consumed" or lease.consumed_at_utc is not None:
            raise RuntimeInputLeaseError(reason="input_already_consumed", input_id=input_id, agent_role=agent_role)
        if lease.pack.expires_at_utc < datetime.now(UTC):
            raise RuntimeInputLeaseError(reason="input_expired", input_id=input_id, agent_role=agent_role)
        return lease

    def _consume_runtime_lease(self, *, lease: AgentRuntimeLease, submission_kind: str) -> None:
        updated = lease.model_copy(update={"status": "consumed", "consumed_at_utc": datetime.now(UTC)})
        self.state_memory.save_asset(
            asset_type="agent_runtime_lease",
            asset_id=lease.pack.input_id,
            payload=updated.model_dump(mode="json"),
            trace_id=lease.pack.trace_id,
            actor_role="system",
            group_key=lease.pack.agent_role,
            metadata={
                "status": "consumed",
                "trigger_type": lease.pack.trigger_type,
                "expires_at_utc": lease.pack.expires_at_utc.isoformat(),
                "submission_kind": submission_kind,
            },
        )
        if self.trigger_bridge is not None:
            self.trigger_bridge.record_runtime_pack_consumed(
                input_id=lease.pack.input_id,
                trace_id=lease.pack.trace_id,
                agent_role=lease.pack.agent_role,
                submission_kind=submission_kind,
            )

    def _record_events(self, events) -> None:
        pending = list(events)
        while pending:
            event = pending.pop(0)
            self.state_memory.append_event(event)
            self._publish_best_effort(event)
            if self.notification_service is not None:
                pending.extend(self.notification_service.handle_event(event))

    def _publish_best_effort(self, event) -> None:
        if self.event_bus is None:
            return None
        try:
            self.event_bus.publish(event)
        except Exception:
            return None

    @staticmethod
    def _build_direct_reminders_from_news(canonical_news: dict[str, Any]) -> list[DirectAgentReminder]:
        reminders: list[DirectAgentReminder] = []
        for item in list(canonical_news.get("events") or []):
            if str(item.get("impact_level") or "").lower() != "high":
                continue
            for role in ("pm", "risk_trader"):
                reminders.append(
                    DirectAgentReminder(
                        reminder_id=new_id("reminder"),
                        from_agent_role="macro_event_analyst",
                        to_agent_role=role,
                        importance="high",
                        message=str(item.get("summary") or ""),
                    )
                )
        return reminders

    def build_runtime_inputs(
        self,
        *,
        trace_id: str,
        market: DataIngestBundle,
        policies: dict[str, GuardDecision],
        forecasts: dict[str, CoinForecast],
        news_events: list[NewsDigestEvent],
        strategy: Any | None = None,
        execution_contexts: list[Any] | None = None,
        latest_strategy: dict | None = None,
        macro_memory: list[dict] | None = None,
    ) -> dict[str, AgentRuntimeInput]:
        strategy_payload = latest_strategy["payload"] if latest_strategy and "payload" in latest_strategy else latest_strategy
        if strategy_payload is None and strategy is not None:
            strategy_payload = strategy.model_dump(mode="json") if hasattr(strategy, "model_dump") else dict(strategy)
        rt_strategy_payload = self._compact_strategy_payload(strategy_payload, agent_role="risk_trader")
        chief_strategy_payload = self._compact_strategy_payload(strategy_payload, agent_role="crypto_chief")
        pm_market_payload = self._compact_market_payload(market, agent_role="pm")
        rt_market_payload = self._compact_market_payload(market, agent_role="risk_trader")
        mea_market_payload = self._compact_market_payload(market, agent_role="macro_event_analyst")
        chief_market_payload = self._compact_market_payload(market, agent_role="crypto_chief")
        compiled_execution_contexts = execution_contexts or self.compile_execution_contexts(
            market=market,
            policies=policies,
            forecasts=forecasts,
            strategy_payload=strategy_payload,
        )
        rt_execution_contexts = self._compact_execution_contexts(compiled_execution_contexts, agent_role="risk_trader")
        chief_execution_contexts = self._compact_execution_contexts(compiled_execution_contexts, agent_role="crypto_chief")
        pm_payload = {
            "trace_id": trace_id,
            "market": pm_market_payload,
            "risk_limits": {coin: self._policy_payload(policy) for coin, policy in policies.items()},
            "forecasts": self._forecast_payload(forecasts),
            "news_events": [item.model_dump(mode="json") for item in news_events],
            "previous_strategy": strategy_payload or {},
            "macro_memory": list(macro_memory or []),
        }
        return {
            "pm": AgentRuntimeInput(
                input_id=new_id("input"),
                agent_role="pm",
                task_kind="strategy",
                payload=pm_payload,
            ),
            "risk_trader": AgentRuntimeInput(
                input_id=new_id("input"),
                agent_role="risk_trader",
                task_kind="execution",
                payload={
                    "trace_id": trace_id,
                    "market": rt_market_payload,
                    "risk_limits": {coin: self._policy_payload(policy) for coin, policy in policies.items()},
                    "forecasts": self._forecast_payload(forecasts),
                    "strategy": rt_strategy_payload,
                    "execution_contexts": rt_execution_contexts,
                },
            ),
            "macro_event_analyst": AgentRuntimeInput(
                input_id=new_id("input"),
                agent_role="macro_event_analyst",
                task_kind="event_summary",
                payload={
                    "trace_id": trace_id,
                    "market": mea_market_payload,
                    "news_events": [item.model_dump(mode="json") for item in news_events],
                    "macro_memory": list(macro_memory or []),
                },
            ),
            "crypto_chief": AgentRuntimeInput(
                input_id=new_id("input"),
                agent_role="crypto_chief",
                task_kind="retro",
                payload={
                    **{**pm_payload, "market": chief_market_payload},
                    "previous_strategy": chief_strategy_payload,
                    "execution_contexts": chief_execution_contexts,
                },
            ),
        }

    def compile_execution_contexts(
        self,
        *,
        market: DataIngestBundle,
        policies: dict[str, GuardDecision],
        forecasts: dict[str, CoinForecast],
        strategy_payload: dict | None,
    ) -> list[dict[str, Any]]:
        if not strategy_payload:
            return []
        total_equity = float(market.portfolio.total_equity_usd or 0.0)
        contexts: list[dict[str, Any]] = []
        for target in strategy_payload.get("targets", []):
            if not isinstance(target, dict):
                continue
            coin = str(target.get("symbol") or "").upper()
            account = market.accounts.get(coin)
            snapshot = market.market.get(coin)
            if not coin or account is None or snapshot is None or coin not in policies:
                continue
            current_share = notional_to_pct_of_exposure_budget(
                notional_usd=account.current_notional_usd,
                total_equity_usd=total_equity,
                max_leverage=policies[coin].risk_limits.max_leverage,
            )
            contexts.append(
                {
                    "context_id": new_id("execctx"),
                    "strategy_id": strategy_payload.get("strategy_id"),
                    "coin": coin,
                    "product_id": snapshot.product_id,
                    "target": target,
                    "current_position_share_pct": round(current_share, 4),
                    "market_snapshot": snapshot.model_dump(mode="json"),
                    "account_snapshot": account.model_dump(mode="json"),
                    "risk_limits": policies[coin].risk_limits.model_dump(mode="json"),
                    "position_risk_state": policies[coin].position_risk_state.model_dump(mode="json"),
                    "forecast_snapshot": self._forecast_payload({coin: forecasts[coin]}).get(coin, {}),
                    "product_metadata": market.product_metadata.get(coin).model_dump(mode="json")
                    if coin in market.product_metadata
                    else {},
                    "execution_history": market.execution_history.get(coin).model_dump(mode="json")
                    if coin in market.execution_history
                    else {},
                }
            )
        return contexts

    def run_pm_submission(self, *, trace_id: str, runtime_input: AgentRuntimeInput) -> ValidatedSubmissionEnvelope:
        return self._run_submission_with_retry(
            trace_id=trace_id,
            runtime_input=runtime_input,
            submission_kind="strategy",
            agent_role="pm",
            task_kind="strategy",
            runner=self.pm_runner,
        )

    def run_rt_submission(self, *, trace_id: str, runtime_input: AgentRuntimeInput) -> ValidatedSubmissionEnvelope:
        return self._run_submission_with_retry(
            trace_id=trace_id,
            runtime_input=runtime_input,
            submission_kind="execution",
            agent_role="risk_trader",
            task_kind="execution",
            runner=self.risk_runner,
        )

    def run_mea_submission(
        self,
        *,
        trace_id: str,
        runtime_input: AgentRuntimeInput,
    ) -> tuple[ValidatedSubmissionEnvelope, list[DirectAgentReminder]]:
        envelope = self._run_submission_with_retry(
            trace_id=trace_id,
            runtime_input=runtime_input,
            submission_kind="news",
            agent_role="macro_event_analyst",
            task_kind="event_summary",
            runner=self.macro_runner,
        )
        reminders: list[DirectAgentReminder] = []
        news_payload = NewsSubmission.model_validate(envelope.payload)
        for item in news_payload.events:
            if item.impact_level != "high":
                continue
            for target_role in ("pm", "risk_trader"):
                reminders.append(
                    DirectAgentReminder(
                        reminder_id=new_id("reminder"),
                        from_agent_role="macro_event_analyst",
                        to_agent_role=target_role,
                        importance=item.impact_level,
                        message=item.summary,
                    )
                )
        return envelope, reminders

    def run_chief_retro(self, *, trace_id: str, runtime_inputs: dict[str, AgentRuntimeInput]) -> dict[str, Any]:
        meeting_id = new_id("retro")
        transcript: list[RetroTranscriptEntry] = []
        speaker_order = list(self._RETRO_SPEAKER_ORDER)
        transcript_cursors: dict[str, int] = {role: 0 for role in speaker_order}
        runtime_input_sent: set[str] = set()

        for round_index in range(1, self._RETRO_ROUND_COUNT + 1):
            for speaker_role in speaker_order:
                runtime_input = runtime_inputs[speaker_role]
                turn_entry = self._run_retro_turn(
                    trace_id=trace_id,
                    meeting_id=meeting_id,
                    round_index=round_index,
                    speaker_role=speaker_role,
                    runtime_input=runtime_input,
                    transcript=transcript,
                    transcript_seen_count=transcript_cursors.get(speaker_role, 0),
                    include_runtime_input=speaker_role not in runtime_input_sent,
                )
                transcript.append(turn_entry)
                transcript_cursors[speaker_role] = len(transcript)
                runtime_input_sent.add(speaker_role)

        learning_targets = self._capture_retro_learning_targets()

        chief_payload = self._run_retro_summary(
            trace_id=trace_id,
            meeting_id=meeting_id,
            runtime_input=runtime_inputs["crypto_chief"],
            transcript=transcript,
            learning_targets=learning_targets,
        )
        learning_results = list(chief_payload.get("learning_results") or [])
        result = RetroMeetingResult(
            meeting_id=meeting_id,
            round_count=self._RETRO_ROUND_COUNT,
            transcript=transcript,
            learning_results=learning_results,
            owner_summary=str(chief_payload.get("owner_summary") or "").strip(),
            reset_command=str(chief_payload.get("reset_command") or "/new").strip() or "/new",
            learning_completed=bool(chief_payload.get("learning_completed")),
        )
        if not result.owner_summary:
            raise self._chief_retro_error(
                error_kind="chief_owner_summary_required",
                raw_reply="",
                stderr_summary="",
                errors=["owner_summary_required"],
            )
        return result.model_dump(mode="json")

    def _run_retro_turn(
        self,
        *,
        trace_id: str,
        meeting_id: str,
        round_index: int,
        speaker_role: str,
        runtime_input: AgentRuntimeInput,
        transcript: list[RetroTranscriptEntry],
        transcript_seen_count: int,
        include_runtime_input: bool,
    ) -> RetroTranscriptEntry:
        transcript_delta = transcript[transcript_seen_count:]
        task = AgentTask(
            task_id=new_id("task"),
            agent_role=speaker_role,
            task_kind="retro_turn",
            input_id=runtime_input.input_id,
            trace_id=trace_id,
            session_id=self.session_id_for_role(speaker_role),
            payload={
                "mode": "retro_meeting_turn",
                "meeting_id": meeting_id,
                "round_index": round_index,
                "speaker_role": speaker_role,
                "role_focus": self._RETRO_ROLE_FOCUS[speaker_role],
                "round_count": self._RETRO_ROUND_COUNT,
                "speaker_order": list(self._RETRO_SPEAKER_ORDER),
                "instruction": "You are in a structured internal retro meeting. It is your turn only. Return exactly one pure JSON object with speaker_role and statement. statement must be non-empty. No markdown fences. No explanation outside JSON. This session keeps your earlier meeting context. Read only the new transcript entries included in this turn instead of expecting the full transcript every time.",
                "transcript_mode": "initial_full_pack" if include_runtime_input else "delta_since_last_turn",
                "transcript_seen_count": transcript_seen_count,
                "transcript_total_count": len(transcript),
                "transcript": [item.model_dump(mode="json") for item in transcript_delta],
                "turn": RetroMeetingTurn(
                    meeting_id=meeting_id,
                    round_index=round_index,
                    speaker_role=speaker_role,
                    transcript=transcript_delta,
                    runtime_input_ref=runtime_input.input_id,
                    transcript_seen_count=transcript_seen_count,
                    transcript_total_count=len(transcript),
                    runtime_input_included=include_runtime_input,
                ).model_dump(mode="json"),
            },
        )
        if include_runtime_input:
            task.payload["runtime_input"] = self._build_retro_runtime_summary(
                speaker_role=speaker_role,
                runtime_input=runtime_input,
            )
        reply = self._run_agent_task_with_retry(task=task)
        if reply.status == "needs_escalation":
            raise self._chief_retro_error(
                error_kind=str(reply.meta.get("error_kind") or "agent_process_failed"),
                raw_reply=str(reply.meta.get("stdout") or reply.meta.get("raw") or ""),
                stderr_summary=str(reply.meta.get("stderr") or ""),
                errors=[f"retro_turn_failed:round_{round_index}:{speaker_role}"],
            )
        turn_reply = self._validate_retro_turn_reply(reply.payload, speaker_role=speaker_role)
        if turn_reply is not None:
            return RetroTranscriptEntry(
                round_index=round_index,
                speaker_role=speaker_role,
                statement=turn_reply.statement,
            )

        repair_reply = self._run_agent_task_with_retry(
            task=AgentTask(
                task_id=new_id("task"),
                agent_role=speaker_role,
                task_kind="retro_turn",
                input_id=runtime_input.input_id,
                trace_id=trace_id,
                session_id=self.session_id_for_role(speaker_role),
                reply_contract="repair_json_only",
                payload={
                    "mode": "retro_turn_repair",
                    "instruction": "Return exactly one pure JSON object only with speaker_role and statement. statement must be non-empty. No markdown fences. No explanation. Use the same meeting context already in this session plus only the new transcript entries included below.",
                    "speaker_role": speaker_role,
                    "round_index": round_index,
                    "role_focus": self._RETRO_ROLE_FOCUS[speaker_role],
                    "previous_reply": reply.meta.get("stdout"),
                    "transcript_mode": "delta_since_last_turn",
                    "transcript_seen_count": transcript_seen_count,
                    "transcript_total_count": len(transcript),
                    "transcript": [item.model_dump(mode="json") for item in transcript_delta],
                },
            )
        )
        if repair_reply.status == "needs_escalation":
            raise self._chief_retro_error(
                error_kind=str(repair_reply.meta.get("error_kind") or "agent_process_failed"),
                raw_reply=str(repair_reply.meta.get("stdout") or repair_reply.meta.get("raw") or ""),
                stderr_summary=str(repair_reply.meta.get("stderr") or ""),
                errors=[f"retro_turn_failed:round_{round_index}:{speaker_role}"],
            )
        repaired_turn = self._validate_retro_turn_reply(repair_reply.payload, speaker_role=speaker_role)
        if repaired_turn is None:
            raise self._chief_retro_error(
                error_kind="retro_turn_invalid",
                raw_reply=str(repair_reply.meta.get("stdout") or repair_reply.meta.get("raw") or ""),
                stderr_summary=str(repair_reply.meta.get("stderr") or ""),
                errors=[f"retro_turn_invalid:round_{round_index}:{speaker_role}"],
            )
        return RetroTranscriptEntry(
            round_index=round_index,
            speaker_role=speaker_role,
            statement=repaired_turn.statement,
        )

    def _build_retro_runtime_summary(
        self,
        *,
        speaker_role: str,
        runtime_input: AgentRuntimeInput,
    ) -> dict[str, Any]:
        payload = dict(runtime_input.payload or {})
        source = dict(payload.get("retro_pack") or payload)
        summary: dict[str, Any] = {
            "trace_id": str(payload.get("trace_id") or source.get("trace_id") or ""),
            "speaker_role": speaker_role,
        }
        trigger_context = payload.get("trigger_context") or source.get("trigger_context")
        if trigger_context:
            summary["trigger_context"] = trigger_context
        market_summary = self._retro_market_summary(source.get("market") or {})
        if market_summary:
            summary["market_summary"] = market_summary
        risk_summary = self._retro_risk_summary(source.get("risk_limits") or {})
        if risk_summary:
            summary["risk_summary"] = risk_summary
        forecast_summary = self._retro_forecast_summary(source.get("forecasts") or {})
        if forecast_summary:
            summary["forecast_summary"] = forecast_summary
        strategy_payload = source.get("strategy") or source.get("previous_strategy") or {}
        strategy_summary = self._retro_strategy_summary(strategy_payload)
        if strategy_summary:
            summary["strategy_summary"] = strategy_summary
        news_summary = self._retro_news_summary(source.get("news_events") or [], limit=8)
        if news_summary:
            summary["news_summary"] = news_summary
        execution_summary = self._retro_execution_context_summary(source.get("execution_contexts") or [])
        if execution_summary:
            summary["execution_context_summary"] = execution_summary
        macro_memory_summary = self._retro_macro_memory_summary(source.get("macro_memory") or [])
        if macro_memory_summary:
            summary["macro_memory_summary"] = macro_memory_summary
        recent_execution_results = source.get("recent_execution_results") or []
        if recent_execution_results:
            summary["recent_execution_results"] = [
                {
                    "run_id": str(item.get("run_id") or ""),
                    "status": str(item.get("status") or ""),
                    "symbol": str(item.get("symbol") or ""),
                    "action": str(item.get("action") or ""),
                    "result_count": len(list(item.get("results") or [])),
                }
                for item in list(recent_execution_results)[:5]
                if isinstance(item, dict)
            ]
        recent_news_submissions = source.get("recent_news_submissions") or []
        if recent_news_submissions:
            summary["recent_news_submissions"] = [
                {
                    "submission_id": str(item.get("submission_id") or ""),
                    "event_count": len(list(item.get("events") or [])),
                }
                for item in list(recent_news_submissions)[:5]
                if isinstance(item, dict)
            ]
        return summary

    def _retro_market_summary(self, market_payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(market_payload or {})
        market = dict(payload.get("market") or {})
        accounts = dict(payload.get("accounts") or {})
        market_context = dict(payload.get("market_context") or {})
        execution_history = dict(payload.get("execution_history") or {})
        summary: dict[str, Any] = {}
        for coin in ("BTC", "ETH", "SOL"):
            snapshot = dict(market.get(coin) or {})
            account = dict(accounts.get(coin) or {})
            context = dict(market_context.get(coin) or {})
            execution = dict(execution_history.get(coin) or {})
            if not snapshot and not account and not context and not execution:
                continue
            summary[coin] = {
                "mark_price": str(snapshot.get("mark_price") or ""),
                "funding_rate": str(snapshot.get("funding_rate") or ""),
                "open_interest": str(snapshot.get("open_interest") or ""),
                "day_notional_volume": str(snapshot.get("day_notional_volume") or ""),
                "trading_status": str(snapshot.get("trading_status") or ""),
                "shape_summary": str(context.get("shape_summary") or ""),
                "breakout_retest_state": str(dict(context.get("breakout_retest_state") or {}).get("state") or ""),
                "volatility_state": str(dict(context.get("volatility_state") or {}).get("state") or ""),
                "current_side": account.get("current_side"),
                "current_notional_usd": account.get("current_notional_usd"),
                "execution_summary": dict(execution.get("summary") or {}),
            }
        portfolio = dict(payload.get("portfolio") or {})
        if portfolio:
            summary["portfolio"] = {
                "total_equity_usd": str(portfolio.get("total_equity_usd") or ""),
                "available_equity_usd": str(portfolio.get("available_equity_usd") or ""),
                "total_exposure_usd": str(portfolio.get("total_exposure_usd") or ""),
                "position_count": len(list(portfolio.get("positions") or [])),
            }
        return summary

    @staticmethod
    def _retro_risk_summary(risk_limits: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for coin, payload in dict(risk_limits or {}).items():
            item = dict(payload or {})
            summary[str(coin)] = {
                "tradable": bool(dict(item.get("trade_availability") or {}).get("tradable", False)),
                "reasons": list(dict(item.get("trade_availability") or {}).get("reasons") or []),
                "max_leverage": dict(item.get("risk_limits") or {}).get("max_leverage"),
                "max_total_exposure_pct_of_equity": dict(item.get("risk_limits") or {}).get("max_total_exposure_pct_of_equity"),
                "max_symbol_position_pct_of_equity": dict(item.get("risk_limits") or {}).get("max_symbol_position_pct_of_equity"),
                "max_order_pct_of_equity": dict(item.get("risk_limits") or {}).get("max_order_pct_of_equity"),
                "position_risk_state": str(dict(item.get("position_risk_state") or {}).get("state") or ""),
                "cooldown_active": bool(dict(item.get("cooldown") or {}).get("active", False)),
                "breaker_active": bool(dict(item.get("breaker") or {}).get("active", False)),
            }
        return summary

    @staticmethod
    def _retro_forecast_summary(forecasts: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for coin, payload in dict(forecasts or {}).items():
            horizon_summary: dict[str, Any] = {}
            for horizon in ("1h", "4h", "12h"):
                item = dict(dict(payload or {}).get(horizon) or {})
                if not item:
                    continue
                horizon_summary[horizon] = {
                    "side": str(item.get("side") or ""),
                    "confidence": item.get("confidence"),
                }
            if horizon_summary:
                summary[str(coin)] = horizon_summary
        return summary

    def _retro_strategy_summary(self, strategy_payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(strategy_payload or {})
        if not payload:
            return {}
        return {
            "strategy_id": str(payload.get("strategy_id") or ""),
            "revision_number": payload.get("revision_number"),
            "portfolio_mode": str(payload.get("portfolio_mode") or ""),
            "target_gross_exposure_band_pct": list(payload.get("target_gross_exposure_band_pct") or []),
            "portfolio_thesis": self._truncate_retro_text(str(payload.get("portfolio_thesis") or ""), 360),
            "portfolio_invalidation": self._truncate_retro_text(str(payload.get("portfolio_invalidation") or ""), 240),
            "change_summary": self._truncate_retro_text(str(payload.get("change_summary") or ""), 240),
            "targets": [
                {
                    "symbol": str(item.get("symbol") or ""),
                    "state": str(item.get("state") or ""),
                    "direction": str(item.get("direction") or ""),
                    "target_exposure_band_pct": list(item.get("target_exposure_band_pct") or []),
                    "rt_discretion_band_pct": item.get("rt_discretion_band_pct"),
                    "no_new_risk": bool(item.get("no_new_risk", False)),
                    "priority": item.get("priority"),
                }
                for item in list(payload.get("targets") or [])
                if isinstance(item, dict)
            ],
            "scheduled_rechecks": [
                {
                    "recheck_at_utc": str(item.get("recheck_at_utc") or ""),
                    "scope": str(item.get("scope") or ""),
                    "reason": self._truncate_retro_text(str(item.get("reason") or ""), 160),
                }
                for item in list(payload.get("scheduled_rechecks") or [])[:3]
                if isinstance(item, dict)
            ],
        }

    def _retro_news_summary(self, news_events: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
        summary: list[dict[str, Any]] = []
        for item in list(news_events or [])[:limit]:
            if not isinstance(item, dict):
                continue
            summary.append(
                {
                    "news_id": str(item.get("news_id") or item.get("event_id") or ""),
                    "title": self._truncate_retro_text(str(item.get("title") or ""), 160),
                    "summary": self._truncate_retro_text(str(item.get("summary") or ""), 220),
                    "severity": str(item.get("severity") or item.get("impact_level") or ""),
                    "published_at": str(item.get("published_at") or item.get("event_time_utc") or ""),
                }
            )
        return summary

    @staticmethod
    def _retro_execution_context_summary(execution_contexts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        summary: list[dict[str, Any]] = []
        for item in list(execution_contexts or []):
            if not isinstance(item, dict):
                continue
            target = dict(item.get("target") or {})
            execution_summary = dict(item.get("execution_summary") or {})
            market_snapshot = dict(item.get("market_snapshot") or {})
            summary.append(
                {
                    "coin": str(item.get("coin") or ""),
                    "product_id": str(item.get("product_id") or ""),
                    "target_state": str(target.get("state") or ""),
                    "direction": str(target.get("direction") or ""),
                    "target_exposure_band_pct": list(target.get("target_exposure_band_pct") or []),
                    "rt_discretion_band_pct": target.get("rt_discretion_band_pct"),
                    "no_new_risk": bool(target.get("no_new_risk", False)),
                    "current_position_share_pct": item.get("current_position_share_pct"),
                    "mark_price": str(market_snapshot.get("mark_price") or ""),
                    "trading_status": str(market_snapshot.get("trading_status") or ""),
                    "execution_summary": execution_summary,
                }
            )
        return summary

    def _retro_macro_memory_summary(self, macro_memory: list[dict[str, Any]]) -> list[dict[str, Any]]:
        summary: list[dict[str, Any]] = []
        for item in list(macro_memory or [])[:5]:
            if not isinstance(item, dict):
                continue
            summary.append(
                {
                    "memory_day_utc": str(item.get("memory_day_utc") or ""),
                    "summary": self._truncate_retro_text(str(item.get("summary") or ""), 220),
                    "event_count": len(list(item.get("event_ids") or [])),
                }
            )
        return summary

    @staticmethod
    def _truncate_retro_text(text: str, limit: int) -> str:
        value = text.strip()
        if len(value) <= limit:
            return value
        return f"{value[: max(0, limit - 1)].rstrip()}…"

    def _run_retro_summary(
        self,
        *,
        trace_id: str,
        meeting_id: str,
        runtime_input: AgentRuntimeInput,
        transcript: list[RetroTranscriptEntry],
        learning_targets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        session_id = self.session_id_for_role("crypto_chief")
        reply = self._run_agent_task_with_retry(
            task=AgentTask(
                task_id=new_id("task"),
                agent_role="crypto_chief",
                task_kind="retro",
                input_id=runtime_input.input_id,
                trace_id=trace_id,
                session_id=session_id,
                payload={
                    "mode": "retro_owner_summary",
                    "meeting_id": meeting_id,
                    "instruction": "The meeting is finished. Use the meeting context already present in this session; do not restate the entire runtime pack or transcript. In each agent's own session, tell them to use /self-improving-agent to record one lesson from this retro into their own canonical learning file. Use the exact session_key provided in each learning_targets item. Do not guess short names like pm or risk_trader. Do not write other agents' learning files yourself. Do not wait for file confirmation and do not block owner communication on learning results. Immediately after sending those requests, return exactly one pure JSON object only with a non-empty owner_summary. You may include optional learning_results if you have them, but they are not required. Do not include reset instructions. No markdown fences. No explanation outside JSON.",
                    "transcript_count": len(transcript),
                    "latest_turns": [item.model_dump(mode="json") for item in transcript[-4:]],
                    "learning_targets": learning_targets,
                },
            )
        )
        if reply.status == "needs_escalation":
            raise self._chief_retro_error(
                error_kind=str(reply.meta.get("error_kind") or "agent_process_failed"),
                raw_reply=str(reply.meta.get("stdout") or reply.meta.get("raw") or ""),
                stderr_summary=str(reply.meta.get("stderr") or ""),
            )
        payload = self._normalize_chief_retro_payload(reply.payload)
        if payload.get("owner_summary"):
            return payload

        repair_reply = self._run_agent_task_with_retry(
            task=AgentTask(
                task_id=new_id("task"),
                agent_role="crypto_chief",
                task_kind="retro",
                input_id=runtime_input.input_id,
                trace_id=trace_id,
                session_id=session_id,
                reply_contract="repair_json_only",
                payload={
                    "mode": "retro_summary_repair",
                    "instruction": "Return exactly one pure JSON object only. Use the meeting context already in this session. owner_summary must be a non-empty string. Ask other agents to run /self-improving-agent using the exact session_key from learning_targets if you have not already done so, but do not wait for completion, do not edit another agent's file yourself, and do not include reset instructions. Optional learning_results may be included, but they are not required. Do not use markdown fences. Do not include explanation.",
                    "previous_reply": reply.meta.get("stdout"),
                    "transcript_count": len(transcript),
                    "latest_turns": [item.model_dump(mode="json") for item in transcript[-4:]],
                    "learning_targets": learning_targets,
                },
            )
        )
        if repair_reply.status == "needs_escalation":
            raise self._chief_retro_error(
                error_kind=str(repair_reply.meta.get("error_kind") or "agent_process_failed"),
                raw_reply=str(repair_reply.meta.get("stdout") or repair_reply.meta.get("raw") or ""),
                stderr_summary=str(repair_reply.meta.get("stderr") or ""),
            )
        payload = self._normalize_chief_retro_payload(repair_reply.payload)
        if payload.get("owner_summary"):
            return payload
        raise self._chief_retro_error(
            error_kind="chief_owner_summary_required",
            raw_reply=str(repair_reply.meta.get("stdout") or repair_reply.meta.get("raw") or ""),
            stderr_summary=str(repair_reply.meta.get("stderr") or ""),
            errors=["owner_summary_required"],
        )

    def _run_agent_task_with_retry(self, *, task: AgentTask) -> AgentReply:
        runner = self._runner_for_role(task.agent_role)
        reply = runner.run(task)
        if reply.status != "needs_escalation" or not self._should_retry_after_session_reset(
            task=task,
            meta=reply.meta,
        ):
            return reply
        reset_result = self.reset_agent_session(
            agent_role=task.agent_role,
            session_id=str(task.session_id or self.session_id_for_role(task.agent_role)),
            reset_command="/new",
        )
        if not bool(reset_result.get("success")):
            return reply
        retried = runner.run(
            AgentTask(
                task_id=new_id("task"),
                agent_role=task.agent_role,
                task_kind=task.task_kind,
                input_id=task.input_id,
                trace_id=task.trace_id,
                session_id=task.session_id,
                reply_contract=task.reply_contract,
                payload=task.payload,
            )
        )
        retried.meta["session_reset_retry"] = reset_result
        return retried

    def validate_submission(
        self,
        *,
        submission_kind: str,
        agent_role: str,
        trace_id: str,
        payload: dict[str, Any],
    ) -> ValidatedSubmissionEnvelope:
        model_cls: type[StrategySubmission | ExecutionSubmission | NewsSubmission]
        if submission_kind == "strategy":
            model_cls = StrategySubmission
        elif submission_kind == "execution":
            model_cls = ExecutionSubmission
        elif submission_kind == "news":
            model_cls = NewsSubmission
        else:  # pragma: no cover - defensive
            raise ValueError(f"unsupported submission kind: {submission_kind}")
        schema_ref, prompt_ref = self._submission_contract(submission_kind)
        if submission_kind == "execution" and isinstance(payload.get("execution"), dict) and "decisions" not in payload:
            raise SubmissionValidationError(
                schema_ref=schema_ref,
                prompt_ref=prompt_ref,
                errors=[
                    (
                        "legacy execution wrapper detected: submit root-level "
                        "`decisions[]`; do not wrap the batch under an `execution` object"
                    )
                ],
            )
        try:
            submission = model_cls.model_validate(payload)
        except Exception as exc:
            raise SubmissionValidationError(
                schema_ref=schema_ref,
                prompt_ref=prompt_ref,
                errors=[str(exc)],
            ) from exc
        return ValidatedSubmissionEnvelope(
            envelope_id=new_id("env"),
            submission_kind=submission_kind,
            trace_id=trace_id,
            agent_role=agent_role,
            schema_ref=schema_ref,
            prompt_ref=prompt_ref,
            payload=submission.model_dump(mode="json"),
        )

    def _run_submission_with_retry(
        self,
        *,
        trace_id: str,
        runtime_input: AgentRuntimeInput,
        submission_kind: str,
        agent_role: str,
        task_kind: str,
        runner,
    ) -> ValidatedSubmissionEnvelope:
        session_id = self.session_id_for_role(agent_role)
        task = AgentTask(
            task_id=new_id("task"),
            agent_role=agent_role,
            task_kind=task_kind,
            input_id=runtime_input.input_id,
            trace_id=trace_id,
            session_id=session_id,
            payload=runtime_input.payload,
        )
        reply = runner.run(task)
        if reply.status == "needs_escalation" and self._should_retry_after_session_reset(
            task=task,
            meta=reply.meta,
        ):
            reset_result = self.reset_agent_session(agent_role=agent_role, session_id=session_id, reset_command="/new")
            if bool(reset_result.get("success")):
                reply = runner.run(
                    AgentTask(
                        task_id=new_id("task"),
                        agent_role=agent_role,
                        task_kind=task_kind,
                        input_id=runtime_input.input_id,
                        trace_id=trace_id,
                        session_id=session_id,
                        payload=runtime_input.payload,
                    )
                )
                reply.meta["session_reset_retry"] = reset_result
        if reply.status == "needs_escalation":
            raise self._transport_error(
                submission_kind=submission_kind,
                error_kind=str(reply.meta.get("error_kind") or "agent_process_failed"),
                meta=reply.meta,
            )
        try:
            if reply.status == "needs_revision":
                raise SubmissionValidationError(
                    schema_ref=self._submission_contract(submission_kind)[0],
                    prompt_ref=self._submission_contract(submission_kind)[1],
                    errors=[str(reply.meta.get("error_kind") or "agent_invalid_transport_payload")],
                    error_kind=str(reply.meta.get("error_kind") or "agent_invalid_transport_payload"),
                    raw_reply=str(reply.meta.get("stdout") or reply.meta.get("raw") or ""),
                    stderr_summary=str(reply.meta.get("stderr") or ""),
                )
            return self.validate_submission(
                submission_kind=submission_kind,
                agent_role=agent_role,
                trace_id=trace_id,
                payload=reply.payload,
            )
        except SubmissionValidationError as exc:
            repair_payload = self._build_repair_payload(
                runtime_input=runtime_input.payload,
                submission_kind=submission_kind,
                schema_ref=exc.schema_ref,
                prompt_ref=exc.prompt_ref,
                errors=exc.errors,
                previous_reply=reply.meta.get("stdout"),
            )
            repair_reply = runner.run(
                AgentTask(
                    task_id=new_id("task"),
                    agent_role=agent_role,
                    task_kind=task_kind,
                    input_id=runtime_input.input_id,
                    trace_id=trace_id,
                    session_id=session_id,
                    reply_contract="repair_json_only",
                    payload=repair_payload,
                )
            )
            if repair_reply.status == "needs_escalation":
                raise self._transport_error(
                    submission_kind=submission_kind,
                    error_kind=str(repair_reply.meta.get("error_kind") or "agent_process_failed"),
                    meta=repair_reply.meta,
                ) from exc
            try:
                return self.validate_submission(
                    submission_kind=submission_kind,
                    agent_role=agent_role,
                    trace_id=trace_id,
                    payload=repair_reply.payload,
                )
            except SubmissionValidationError as repair_exc:
                raise SubmissionValidationError(
                    schema_ref=repair_exc.schema_ref,
                    prompt_ref=repair_exc.prompt_ref,
                    errors=repair_exc.errors,
                    error_kind=str(repair_reply.meta.get("error_kind") or repair_exc.error_kind),
                    raw_reply=str(repair_reply.meta.get("stdout") or repair_reply.meta.get("raw") or ""),
                    stderr_summary=str(repair_reply.meta.get("stderr") or ""),
                ) from exc

    def _transport_error(self, *, submission_kind: str, error_kind: str, meta: dict[str, Any]) -> SubmissionValidationError:
        schema_ref, prompt_ref = self._submission_contract(submission_kind)
        return SubmissionValidationError(
            schema_ref=schema_ref,
            prompt_ref=prompt_ref,
            errors=[error_kind],
            error_kind=error_kind,
            raw_reply=str(meta.get("stdout") or meta.get("raw") or ""),
            stderr_summary=str(meta.get("stderr") or ""),
        )

    def _submission_contract(self, submission_kind: str) -> tuple[str, str]:
        if submission_kind == "strategy":
            return self._STRATEGY_SCHEMA_REF, self._STRATEGY_PROMPT_REF
        if submission_kind == "execution":
            return self._EXECUTION_SCHEMA_REF, self._EXECUTION_PROMPT_REF
        if submission_kind == "news":
            return self._NEWS_SCHEMA_REF, self._NEWS_PROMPT_REF
        raise ValueError(f"unsupported submission kind: {submission_kind}")

    @classmethod
    def _chief_retro_error(
        cls,
        *,
        error_kind: str,
        raw_reply: str,
        stderr_summary: str,
        errors: list[str] | None = None,
    ) -> SubmissionValidationError:
        return SubmissionValidationError(
            schema_ref=cls._CHIEF_RETRO_SPEC_REF,
            prompt_ref=cls._CHIEF_RETRO_PROMPT_REF,
            errors=list(errors or [error_kind]),
            error_kind=error_kind,
            raw_reply=raw_reply,
            stderr_summary=stderr_summary,
        )

    @staticmethod
    def _normalize_chief_retro_payload(payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload or {})
        normalized["owner_summary"] = str(normalized.get("owner_summary") or "").strip()
        normalized["reset_command"] = str(normalized.get("reset_command") or "/new").strip() or "/new"
        normalized["learning_completed"] = bool(normalized.get("learning_completed"))
        normalized["learning_results"] = list(normalized.get("learning_results") or [])
        return normalized

    @staticmethod
    def _validate_retro_turn_reply(payload: dict[str, Any], *, speaker_role: str) -> RetroTurnReply | None:
        normalized = dict(payload or {})
        normalized["speaker_role"] = str(normalized.get("speaker_role") or speaker_role).strip() or speaker_role
        normalized["statement"] = str(normalized.get("statement") or "").strip()
        if normalized["speaker_role"] != speaker_role or not normalized["statement"]:
            return None
        try:
            return RetroTurnReply.model_validate(normalized)
        except Exception:
            return None

    @staticmethod
    def _validate_retro_learning_ack(
        payload: dict[str, Any],
        *,
        agent_role: str,
        learning_path: str,
    ) -> RetroLearningAck | None:
        normalized = dict(payload or {})
        normalized["agent_role"] = str(normalized.get("agent_role") or agent_role).strip() or agent_role
        normalized["learning_path"] = str(normalized.get("learning_path") or learning_path).strip() or learning_path
        normalized["learning_summary"] = str(normalized.get("learning_summary") or "").strip()
        normalized["learning_updated"] = bool(normalized.get("learning_updated"))
        if normalized["agent_role"] != agent_role or normalized["learning_path"] != learning_path:
            return None
        if not normalized["learning_updated"] or not normalized["learning_summary"]:
            return None
        try:
            return RetroLearningAck.model_validate(normalized)
        except Exception:
            return None

    def _capture_retro_learning_targets(self) -> list[dict[str, Any]]:
        return [
            {
                "agent_role": agent_role,
                "session_key": f"agent:{self.agent_name_by_role.get(agent_role, self._DEFAULT_AGENT_NAME_BY_ROLE[agent_role])}:main",
                "learning_path": self.learning_path_by_role.get(agent_role, self._DEFAULT_LEARNING_PATH_BY_ROLE[agent_role]),
                "baseline": self._learning_file_fingerprint(
                    self.learning_path_by_role.get(agent_role, self._DEFAULT_LEARNING_PATH_BY_ROLE[agent_role])
                ),
            }
            for agent_role in self._RETRO_SPEAKER_ORDER
        ]

    def _validate_retro_learning_results(
        self,
        payload_results: list[dict[str, Any]],
        *,
        learning_targets: list[dict[str, Any]],
    ) -> list[RetroLearningAck]:
        errors: list[str] = []
        validated: list[RetroLearningAck] = []
        results_by_role = {
            str(item.get("agent_role") or "").strip(): item
            for item in list(payload_results or [])
            if isinstance(item, dict)
        }
        for target in learning_targets:
            agent_role = str(target["agent_role"])
            learning_path = str(target["learning_path"])
            result_payload = results_by_role.get(agent_role)
            if result_payload is None:
                errors.append(f"learning_missing:{agent_role}")
                continue
            learning_ack = self._validate_retro_learning_ack(
                result_payload,
                agent_role=agent_role,
                learning_path=learning_path,
            )
            if learning_ack is None:
                errors.append(f"learning_result_invalid:{agent_role}")
                continue
            current_state = self._learning_file_fingerprint(learning_path)
            if not self._learning_file_changed(
                baseline=dict(target.get("baseline") or {}),
                current_state=current_state,
            ):
                errors.append(f"learning_file_unchanged:{agent_role}")
                continue
            validated.append(learning_ack)
        if errors:
            raise self._chief_retro_error(
                error_kind="retro_learning_verification_failed",
                raw_reply="",
                stderr_summary="",
                errors=errors,
            )
        return validated

    @staticmethod
    def _learning_file_fingerprint(learning_path: str) -> dict[str, Any]:
        path = Path(learning_path)
        if not path.exists():
            return {
                "exists": False,
                "mtime_ns": None,
                "size_bytes": 0,
                "content_sha256": None,
            }
        try:
            content = path.read_bytes()
        except OSError:
            content = b""
        stat = path.stat()
        return {
            "exists": True,
            "mtime_ns": stat.st_mtime_ns,
            "size_bytes": stat.st_size,
            "content_sha256": hashlib.sha256(content).hexdigest(),
        }

    @staticmethod
    def _learning_file_changed(*, baseline: dict[str, Any], current_state: dict[str, Any]) -> bool:
        if not bool(current_state.get("exists")) or int(current_state.get("size_bytes") or 0) <= 0:
            return False
        if not bool(baseline.get("exists")):
            return True
        return any(
            current_state.get(key) != baseline.get(key)
            for key in ("mtime_ns", "size_bytes", "content_sha256")
        )

    def _runner_for_role(self, agent_role: str) -> AgentRunner:
        if agent_role == "pm":
            return self.pm_runner
        if agent_role == "risk_trader":
            return self.risk_runner
        if agent_role == "macro_event_analyst":
            return self.macro_runner
        if agent_role == "crypto_chief":
            return self.chief_runner
        raise ValueError(f"unsupported agent role: {agent_role}")

    @staticmethod
    def _build_repair_payload(
        *,
        runtime_input: dict[str, Any],
        submission_kind: str,
        schema_ref: str,
        prompt_ref: str,
        errors: list[str],
        previous_reply: object,
    ) -> dict[str, Any]:
        return {
            "mode": "schema_repair",
            "submission_kind": submission_kind,
            "instruction": "The previous formal submission failed validation. Return exactly one pure JSON object only. Do not use markdown fences. Do not include any explanation.",
            "schema_ref": schema_ref,
            "prompt_ref": prompt_ref,
            "validation_errors": list(errors),
            "previous_reply": previous_reply,
            "original_runtime_input": runtime_input,
        }

    def request_execution_decisions(
        self,
        *,
        trace_id: str,
        runtime_input: AgentRuntimeInput,
        execution_contexts: list[Any],
    ) -> list[ExecutionDecision]:
        payload = dict(runtime_input.payload)
        payload["execution_contexts"] = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
            for item in execution_contexts
        ]
        envelope = self.run_rt_submission(
            trace_id=trace_id,
            runtime_input=AgentRuntimeInput(
                input_id=runtime_input.input_id,
                agent_role=runtime_input.agent_role,
                task_kind=runtime_input.task_kind,
                payload=payload,
            ),
        )
        decisions: list[ExecutionDecision] = []
        execution_submission = ExecutionSubmission.model_validate(envelope.payload)
        for item in execution_submission.decisions:
            decisions.append(
                ExecutionDecision(
                    decision_id=execution_submission.decision_id,
                    strategy_version=execution_submission.strategy_id or "unknown",
                    context_id=new_id("execctx"),
                    product_id=f"{item.symbol}-PERP-INTX",
                    coin=item.symbol,
                    action=item.action,
                    side=item.direction or ("flat" if item.action in {"wait", "hold"} else "long"),
                    size_pct_of_equity=item.size_pct_of_equity,
                    urgency=item.urgency,
                    valid_for_minutes=item.valid_for_minutes,
                    reason=item.reason,
                    priority=item.priority,
                    escalate_to_pm=item.escalate_to_pm,
                    escalation_reason=item.escalation_reason,
                )
            )
        return decisions

    def build_submission_event(self, *, trace_id: str, envelope: ValidatedSubmissionEnvelope):
        return EventFactory.build(
            trace_id=trace_id,
            event_type=EVENT_SUBMISSION_VALIDATED,
            source_module=MODULE_NAME,
            entity_type="validated_submission",
            entity_id=envelope.envelope_id,
            payload=envelope.model_dump(mode="json"),
        )

    def build_submission_error_event(self, *, trace_id: str, agent_role: str, error: SubmissionValidationError):
        return EventFactory.build(
            trace_id=trace_id,
            event_type=EVENT_SUBMISSION_REJECTED,
            source_module=MODULE_NAME,
            entity_type="submission_error",
            entity_id=new_id("submission_error"),
            payload={
                "agent_role": agent_role,
                "schema_ref": error.schema_ref,
                "prompt_ref": error.prompt_ref,
                "errors": error.errors,
                "error_kind": error.error_kind,
                "raw_reply": error.raw_reply,
                "stderr_summary": error.stderr_summary,
            },
        )

    def build_session_reset_event(
        self,
        *,
        trace_id: str,
        agent_role: str,
        session_id: str,
        result: dict[str, object] | None = None,
    ):
        return EventFactory.build(
            trace_id=trace_id,
            event_type=EVENT_AGENT_SESSION_RESET,
            source_module=MODULE_NAME,
            entity_type="agent_session",
            entity_id=session_id,
            payload={
                "agent_role": agent_role,
                "session_id": session_id,
                "reset_command": "/new",
                "result": result or {},
            },
        )

    def reset_agent_session(self, *, agent_role: str, session_id: str, reset_command: str = "/new") -> dict[str, object]:
        if self.session_controller is None:
            return {
                "agent_role": agent_role,
                "session_id": session_id,
                "reset_command": reset_command,
                "success": False,
                "error": "session_controller_not_configured",
            }
        return self.session_controller.reset(agent_role=agent_role, session_id=session_id, reset_command=reset_command)

    @staticmethod
    def _forecast_payload(forecasts: dict[str, CoinForecast]) -> dict[str, dict[str, dict[str, float | str]]]:
        payload: dict[str, dict[str, dict[str, float | str]]] = {}
        for coin, forecast in forecasts.items():
            per_coin: dict[str, dict[str, float | str]] = {}
            for horizon in ("1h", "4h", "12h"):
                signal = forecast.horizons.get(horizon)
                if signal is None:
                    continue
                per_coin[horizon] = {"side": signal.side, "confidence": round(float(signal.confidence), 4)}
            payload[coin] = per_coin
        return payload

    @staticmethod
    def _policy_payload(policy: GuardDecision) -> dict[str, object]:
        payload = policy.model_dump(mode="json")
        diagnostics = payload.get("diagnostics")
        if isinstance(diagnostics, dict):
            diagnostics.pop("ignored_horizons", None)
        return payload

    @staticmethod
    def default_recheck_at(hours: int = 4) -> datetime:
        return datetime.now(UTC) + timedelta(hours=hours)

    @staticmethod
    def today_utc() -> str:
        return date.today().isoformat()

    @classmethod
    def _compact_market_payload(cls, market: DataIngestBundle, *, agent_role: str) -> dict[str, Any]:
        payload = cls._strip_raw_fields(market.model_dump(mode="json"))
        price_point_limit = cls._PRICE_POINT_LIMIT_BY_ROLE.get(agent_role, 12)
        execution_limit = cls._EXECUTION_SAMPLE_LIMIT_BY_ROLE.get(agent_role, 3)
        payload["market_context"] = cls._compact_market_context(payload.get("market_context", {}), point_limit=price_point_limit)
        payload["product_metadata"] = cls._compact_product_metadata(payload.get("product_metadata", {}))
        payload["accounts"] = cls._compact_accounts(payload.get("accounts", {}))
        payload["portfolio"] = cls._compact_portfolio(payload.get("portfolio", {}))
        if execution_limit <= 0:
            payload.pop("execution_history", None)
        else:
            payload["execution_history"] = cls._compact_execution_history(
                payload.get("execution_history", {}),
                sample_limit=execution_limit,
            )
        if agent_role == "macro_event_analyst":
            payload.pop("accounts", None)
            payload.pop("portfolio", None)
        return payload

    @classmethod
    def _compact_strategy_payload(cls, payload: dict[str, Any] | None, *, agent_role: str) -> dict[str, Any]:
        if not payload:
            return {}
        keep_keys_by_role = {
            "risk_trader": {
                "strategy_id",
                "strategy_version",
                "strategy_day_utc",
                "generated_at_utc",
                "trigger_type",
                "revision_number",
                "portfolio_mode",
                "target_gross_exposure_band_pct",
                "portfolio_thesis",
                "portfolio_invalidation",
                "change_summary",
                "targets",
            },
            "crypto_chief": {
                "strategy_id",
                "strategy_day_utc",
                "generated_at_utc",
                "trigger_type",
                "supersedes_strategy_id",
                "revision_number",
                "portfolio_mode",
                "target_gross_exposure_band_pct",
                "portfolio_thesis",
                "portfolio_invalidation",
                "change_summary",
                "targets",
                "scheduled_rechecks",
            },
        }
        keep_keys = keep_keys_by_role.get(agent_role)
        if not keep_keys:
            return dict(payload)
        return {key: value for key, value in payload.items() if key in keep_keys}

    @classmethod
    def _compact_execution_contexts(cls, contexts: list[Any], *, agent_role: str) -> list[dict[str, Any]]:
        compacted: list[dict[str, Any]] = []
        for item in contexts:
            payload = item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item or {})
            current_position_share_pct = payload.get("current_position_share_pct")
            if current_position_share_pct is None:
                current_position_share_pct = dict(payload.get("account_snapshot") or {}).get("current_position_share_pct")
            if agent_role == "risk_trader":
                compacted.append(
                    {
                        "context_id": payload.get("context_id"),
                        "strategy_id": payload.get("strategy_id"),
                        "coin": payload.get("coin"),
                        "product_id": payload.get("product_id"),
                        "target": cls._compact_strategy_target(payload.get("target")),
                        "current_position_share_pct": current_position_share_pct,
                        "market_snapshot": cls._compact_execution_market_snapshot(payload.get("market_snapshot")),
                        "account_snapshot": cls._compact_execution_account_snapshot(payload.get("account_snapshot")),
                        "product_metadata": cls._compact_execution_product_metadata(payload.get("product_metadata")),
                        "execution_summary": cls._compact_execution_summary(payload.get("execution_history")),
                    }
                )
                continue
            compacted.append(payload)
        return compacted

    @staticmethod
    def _compact_strategy_target(payload: dict[str, Any] | None) -> dict[str, Any]:
        keep_keys = {
            "symbol",
            "state",
            "direction",
            "target_exposure_band_pct",
            "rt_discretion_band_pct",
            "no_new_risk",
            "priority",
        }
        return {
            key: value for key, value in dict(payload or {}).items() if key in keep_keys
        }

    @staticmethod
    def _compact_execution_market_snapshot(payload: dict[str, Any] | None) -> dict[str, Any]:
        keep_keys = {
            "product_id",
            "mark_price",
            "index_price",
            "best_bid",
            "best_ask",
            "spread_bps",
            "funding_rate",
            "premium",
            "open_interest",
            "day_notional_volume",
            "day_price_change_pct",
            "trading_status",
            "captured_at",
        }
        return {key: value for key, value in dict(payload or {}).items() if key in keep_keys}

    @staticmethod
    def _compact_execution_account_snapshot(payload: dict[str, Any] | None) -> dict[str, Any]:
        keep_keys = {
            "coin",
            "current_side",
            "current_notional_usd",
            "current_quantity",
            "current_leverage",
            "entry_price",
            "unrealized_pnl_usd",
            "liquidation_price",
            "available_equity_usd",
            "captured_at",
        }
        return {key: value for key, value in dict(payload or {}).items() if key in keep_keys}

    @staticmethod
    def _compact_execution_product_metadata(payload: dict[str, Any] | None) -> dict[str, Any]:
        keep_keys = {
            "coin",
            "product_id",
            "tick_size",
            "size_increment",
            "min_size",
            "min_notional",
            "max_leverage",
            "trading_status",
            "trading_disabled",
            "cancel_only",
            "limit_only",
            "post_only",
        }
        return {key: value for key, value in dict(payload or {}).items() if key in keep_keys}

    @staticmethod
    def _compact_execution_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
        history = dict(payload or {})
        summary = dict(history.get("summary") or {})
        if not summary:
            summary = {
                "recent_order_count": len(history.get("recent_orders", [])),
                "recent_fill_count": len(history.get("recent_fills", [])),
                "open_order_count": len(history.get("open_orders", [])),
                "failure_count": len(history.get("failure_sources", [])),
            }
        return summary

    @staticmethod
    def _should_retry_after_session_reset(*, task: AgentTask, meta: dict[str, Any]) -> bool:
        if str(meta.get("error_kind") or "") == "agent_timeout":
            if task.task_kind == "retro_turn":
                return True
            if task.agent_role in {"risk_trader", "crypto_chief"}:
                return True
        if task.task_kind == "retro_turn" and str(meta.get("error_kind") or "") == "agent_process_failed":
            return True
        haystack = " ".join(
            str(meta.get(key) or "")
            for key in ("stderr", "stdout", "raw")
        ).lower()
        markers = (
            "range of input length",
            "input length should be",
            "maximum context length",
            "too many context tokens",
            "context length exceeded",
        )
        return any(marker in haystack for marker in markers)

    @classmethod
    def _strip_raw_fields(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: cls._strip_raw_fields(nested)
                for key, nested in value.items()
                if key != "raw"
            }
        if isinstance(value, list):
            return [cls._strip_raw_fields(item) for item in value]
        return value

    @classmethod
    def _compact_market_context(cls, payload: dict[str, Any], *, point_limit: int) -> dict[str, Any]:
        compacted: dict[str, Any] = {}
        for coin, context in payload.items():
            context_payload = dict(context)
            compressed = {}
            for window, series in (context_payload.get("compressed_price_series") or {}).items():
                series_payload = dict(series)
                points = list(series_payload.get("points") or [])
                if point_limit > 0 and len(points) > point_limit:
                    series_payload["points"] = points[-point_limit:]
                compressed[window] = series_payload
            context_payload["compressed_price_series"] = compressed
            compacted[coin] = context_payload
        return compacted

    @staticmethod
    def _compact_product_metadata(payload: dict[str, Any]) -> dict[str, Any]:
        keep_keys = {
            "coin",
            "product_id",
            "tick_size",
            "size_increment",
            "min_size",
            "min_notional",
            "max_leverage",
            "trading_status",
            "trading_disabled",
            "cancel_only",
            "limit_only",
            "post_only",
            "captured_at",
        }
        return {
            coin: {key: value for key, value in snapshot.items() if key in keep_keys}
            for coin, snapshot in payload.items()
        }

    @staticmethod
    def _compact_accounts(payload: dict[str, Any]) -> dict[str, Any]:
        keep_keys = {
            "coin",
            "total_equity_usd",
            "available_equity_usd",
            "current_side",
            "current_notional_usd",
            "current_leverage",
            "current_quantity",
            "entry_price",
            "unrealized_pnl_usd",
            "liquidation_price",
            "captured_at",
        }
        return {
            coin: {key: value for key, value in snapshot.items() if key in keep_keys}
            for coin, snapshot in payload.items()
        }

    @staticmethod
    def _compact_portfolio(payload: dict[str, Any]) -> dict[str, Any]:
        keep_keys = {
            "starting_equity_usd",
            "realized_pnl_usd",
            "unrealized_pnl_usd",
            "total_equity_usd",
            "available_equity_usd",
            "total_exposure_usd",
            "open_order_hold_usd",
            "positions",
            "captured_at",
        }
        position_keys = {
            "coin",
            "side",
            "quantity",
            "notional_usd",
            "leverage",
            "entry_price",
            "unrealized_pnl_usd",
            "position_share_pct_of_equity",
            "opened_at",
        }
        compacted = {key: value for key, value in payload.items() if key in keep_keys}
        compacted["positions"] = [
            {key: value for key, value in position.items() if key in position_keys}
            for position in payload.get("positions", [])
        ]
        return compacted

    @classmethod
    def _compact_execution_history(cls, payload: dict[str, Any], *, sample_limit: int) -> dict[str, Any]:
        compacted: dict[str, Any] = {}
        for coin, history in payload.items():
            compacted[coin] = {
                "coin": history.get("coin"),
                "product_id": history.get("product_id"),
                "captured_at": history.get("captured_at"),
                "recent_orders": cls._sample_records(
                    history.get("recent_orders", []),
                    sample_limit=sample_limit,
                    keep_keys={
                        "order_id",
                        "product_id",
                        "side",
                        "status",
                        "order_type",
                        "created_time",
                        "filled_size",
                        "average_filled_price",
                        "filled_value",
                        "reject_reason",
                        "reject_message",
                        "outstanding_hold_amount",
                        "leverage",
                        "last_fill_time",
                        "last_update_time",
                    },
                ),
                "recent_fills": cls._sample_records(
                    history.get("recent_fills", []),
                    sample_limit=sample_limit,
                    keep_keys={
                        "trade_id",
                        "order_id",
                        "trade_time",
                        "trade_type",
                        "price",
                        "size",
                        "commission",
                        "product_id",
                        "side",
                        "liquidity_indicator",
                    },
                ),
                "open_orders": cls._sample_records(
                    history.get("open_orders", []),
                    sample_limit=sample_limit,
                    keep_keys={
                        "order_id",
                        "status",
                        "side",
                        "order_type",
                        "notional_usd",
                        "limit_price",
                        "base_size",
                        "created_at",
                    },
                ),
                "failure_sources": cls._sample_records(
                    history.get("failure_sources", []),
                    sample_limit=sample_limit,
                    keep_keys={
                        "source",
                        "reason",
                        "message",
                        "captured_at",
                        "symbol",
                        "order_id",
                    },
                ),
                "summary": {
                    "recent_order_count": len(history.get("recent_orders", [])),
                    "recent_fill_count": len(history.get("recent_fills", [])),
                    "open_order_count": len(history.get("open_orders", [])),
                    "failure_count": len(history.get("failure_sources", [])),
                },
            }
        return compacted

    @staticmethod
    def _sample_records(records: list[Any], *, sample_limit: int, keep_keys: set[str]) -> list[dict[str, Any]]:
        sampled: list[dict[str, Any]] = []
        for record in list(records)[-sample_limit:]:
            if isinstance(record, dict):
                sampled.append({key: value for key, value in record.items() if key in keep_keys})
        return sampled

    _SESSION_ID_BY_ROLE = {
        "pm": "pm-session",
        "risk_trader": "risk-trader-session",
        "macro_event_analyst": "macro-event-analyst-session",
        "crypto_chief": "crypto-chief-session",
    }
    _DEFAULT_AGENT_NAME_BY_ROLE = {
        "pm": "pm",
        "risk_trader": "risk-trader",
        "macro_event_analyst": "macro-event-analyst",
        "crypto_chief": "crypto-chief",
    }
    _DEFAULT_LEARNING_PATH_BY_ROLE = {
        "pm": str(Path.home() / ".openclaw" / "workspace-pm" / ".learnings" / "pm.md"),
        "risk_trader": str(Path.home() / ".openclaw" / "workspace-risk-trader" / ".learnings" / "risk_trader.md"),
        "macro_event_analyst": str(
            Path.home() / ".openclaw" / "workspace-macro-event-analyst" / ".learnings" / "macro_event_analyst.md"
        ),
        "crypto_chief": str(Path.home() / ".openclaw" / "workspace-crypto-chief" / ".learnings" / "crypto_chief.md"),
    }
    _RETRO_SPEAKER_ORDER = (
        "pm",
        "risk_trader",
        "macro_event_analyst",
        "crypto_chief",
    )
    _RETRO_ROUND_COUNT = 2
    _RETRO_ROLE_FOCUS = {
        "pm": "Explain target state, thesis, what changed, and respond to previous objections from a PM point of view.",
        "risk_trader": "Explain execution quality, deviation, timing, and whether PM intent was tradable from an RT point of view.",
        "macro_event_analyst": "Explain which events mattered, whether reminders were timely, and whether the thesis changed from an MEA point of view.",
        "crypto_chief": "Moderate, attribute outcomes, enforce discipline, challenge weak reasoning, and close the round from a Chief point of view.",
    }
    _PRICE_POINT_LIMIT_BY_ROLE = {
        "pm": 12,
        "risk_trader": 8,
        "macro_event_analyst": 8,
        "crypto_chief": 8,
    }
    _EXECUTION_SAMPLE_LIMIT_BY_ROLE = {
        "pm": 3,
        "risk_trader": 2,
        "macro_event_analyst": 0,
        "crypto_chief": 3,
    }

    def _resolve_openclaw_main_session_id(self, agent_role: str) -> str | None:
        agent_name = self.agent_name_by_role.get(agent_role)
        if not agent_name:
            return None
        store_path = Path.home() / ".openclaw" / "agents" / agent_name / "sessions" / "sessions.json"
        if not store_path.exists():
            return None
        try:
            payload = json.loads(store_path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        entry = payload.get(f"agent:{agent_name}:main")
        if not isinstance(entry, dict):
            return None
        session_id = entry.get("sessionId")
        return session_id if isinstance(session_id, str) and session_id else None
