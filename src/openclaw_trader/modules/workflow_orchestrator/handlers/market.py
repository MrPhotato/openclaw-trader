from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ....shared.protocols import EventFactory
from ....shared.utils import new_id
from ...agent_gateway.models import ExecutionSubmission, NewsSubmission
from ...agent_gateway.service import SubmissionValidationError
from ...trade_gateway.execution.models import ExecutionDecision
from ..models import ManualTriggerCommand
from .base import WorkflowEventRecorder, WorkflowModuleServices


@dataclass
class WorkflowRuntimeContext:
    market: Any
    news: list[Any]
    forecasts: dict[str, Any]
    policies: dict[str, Any]
    latest_strategy: dict[str, Any] | None
    macro_memory: list[dict[str, Any]]
    agent_inputs: dict[str, Any]


class MarketWorkflowHandler(WorkflowEventRecorder):
    def __init__(self, services: WorkflowModuleServices) -> None:
        super().__init__(services)

    def handle(self, command: ManualTriggerCommand, *, workflow_id: str, trace_id: str) -> dict:
        command_type = self._normalize_command(command.command_type.value)
        context = self._collect_runtime_context(command_type=command_type, trace_id=trace_id)

        result: dict[str, Any] = {
            "workflow_id": workflow_id,
            "trace_id": trace_id,
            "sequence_id": new_id("run"),
            "portfolio": context.market.portfolio.model_dump(mode="json"),
            "agent_inputs": {name: item.input_id for name, item in context.agent_inputs.items()},
        }

        if command_type in {"dispatch_once", "run_pm"}:
            pm_result = self._run_pm(trace_id=trace_id, command=command, command_type=command_type, context=context)
            result["strategy"] = pm_result
            if not pm_result.get("degraded"):
                result["strategy_version"] = pm_result["strategy_id"]
                context.latest_strategy = pm_result
            else:
                result["degraded"] = True

        if command_type in {"dispatch_once", "run_pm", "run_rt"} and context.latest_strategy:
            rt_result = self._run_rt(trace_id=trace_id, command=command, context=context)
            result["execution"] = rt_result
            if rt_result.get("degraded"):
                result["degraded"] = True

        if command_type in {"dispatch_once", "run_mea"}:
            mea_result = self._run_mea(trace_id=trace_id, context=context)
            result["macro"] = mea_result

        return result

    def _collect_runtime_context(self, *, command_type: str, trace_id: str) -> WorkflowRuntimeContext:
        market = self.services.market_data.collect(trace_id=trace_id)
        self.record_events(self.services.market_data.build_market_events(market))
        self.services.memory_assets.save_portfolio(trace_id, market.portfolio.model_dump(mode="json"))
        self._persist_market_snapshots(command_type=command_type, trace_id=trace_id, market=market)

        news = self.services.news_events.sync() if command_type in {"dispatch_once", "run_mea"} else self.services.news_events.latest()
        if command_type in {"dispatch_once", "run_mea"}:
            self.record_events([self.services.news_events.build_sync_event(trace_id=trace_id, events=news)])
        self.services.memory_assets.save_asset(
            asset_type="news_batch",
            payload={"events": [item.model_dump(mode="json") for item in news]},
            trace_id=trace_id,
            actor_role="system",
            group_key=trace_id,
        )

        forecasts = self.services.quant_intelligence.predict_market(market)
        self.record_events(self.services.quant_intelligence.build_forecast_events(trace_id=trace_id, forecasts=forecasts))
        self.services.memory_assets.save_asset(
            asset_type="forecast_bundle",
            payload={coin: item.model_dump(mode="json") for coin, item in forecasts.items()},
            trace_id=trace_id,
            actor_role="system",
            group_key=trace_id,
        )

        policies = self.services.policy_risk.evaluate(market=market, forecasts=forecasts, news_events=news)
        self.record_events(self.services.policy_risk.build_policy_events(trace_id=trace_id, policies=policies))
        for coin, policy in policies.items():
            self.services.memory_assets.save_asset(
                asset_type="policy_guard",
                payload=policy.model_dump(mode="json"),
                trace_id=trace_id,
                actor_role="system",
                group_key=coin,
            )

        latest_strategy_asset = self.services.memory_assets.latest_asset(asset_type="strategy")
        latest_strategy = latest_strategy_asset["payload"] if latest_strategy_asset else None
        if latest_strategy is None:
            stored_strategy = self.services.memory_assets.latest_strategy()
            latest_strategy = stored_strategy["payload"] if stored_strategy else None
        macro_memory_assets = self.services.memory_assets.recent_assets(asset_type="macro_daily_memory", limit=5)
        if macro_memory_assets:
            macro_memory = [item["payload"] for item in macro_memory_assets]
        else:
            macro_memory = [item["payload"] for item in self.services.memory_assets.recent_assets(asset_type="macro_event", limit=10)]

        return WorkflowRuntimeContext(
            market=market,
            news=news,
            forecasts=forecasts,
            policies=policies,
            latest_strategy=latest_strategy,
            macro_memory=macro_memory,
            agent_inputs=self.services.agent_gateway.build_runtime_inputs(
                trace_id=trace_id,
                market=market,
                policies=policies,
                forecasts=forecasts,
                news_events=news,
                latest_strategy=latest_strategy,
                macro_memory=macro_memory,
            ),
        )

    def _run_pm(
        self,
        *,
        trace_id: str,
        command: ManualTriggerCommand,
        command_type: str,
        context: WorkflowRuntimeContext,
    ) -> dict[str, Any]:
        session_id = self.services.agent_gateway.session_id_for_role("pm")
        self.services.memory_assets.save_agent_session(
            agent_role="pm",
            session_id=session_id,
            last_task_kind="strategy",
        )
        try:
            envelope = self.services.agent_gateway.run_pm_submission(
                trace_id=trace_id,
                runtime_input=context.agent_inputs["pm"],
            )
        except SubmissionValidationError as exc:
            return self._handle_submission_validation_error(
                trace_id=trace_id,
                agent_role="pm",
                session_id=session_id,
                task_kind="strategy",
                error=exc,
            )
        trigger_type = self._resolve_pm_trigger_type(command=command)
        strategy_payload = self.services.memory_assets.materialize_strategy_asset(
            trace_id=trace_id,
            authored_payload=envelope.payload,
            trigger_type=trigger_type,
            actor_role="pm",
            source_ref=envelope.envelope_id,
        )
        self.record_events(
            [
                self.services.agent_gateway.build_submission_event(trace_id=trace_id, envelope=envelope),
                EventFactory.build(
                    trace_id=trace_id,
                    event_type="strategy.submitted",
                    source_module="agent_gateway",
                    entity_type="strategy",
                    entity_id=str(strategy_payload.get("strategy_id")),
                    payload={
                        "strategy": strategy_payload,
                        "envelope_id": envelope.envelope_id,
                        "trigger_type": trigger_type,
                    },
                ),
            ]
        )
        self.services.memory_assets.save_agent_session(
            agent_role="pm",
            session_id=session_id,
            last_task_kind="strategy",
            last_submission_kind="strategy",
        )
        return strategy_payload

    def _run_rt(self, *, trace_id: str, command: ManualTriggerCommand, context: WorkflowRuntimeContext) -> dict[str, Any]:
        session_id = self.services.agent_gateway.session_id_for_role("risk_trader")
        strategy_payload = context.latest_strategy
        if not strategy_payload:
            return {
                "degraded": True,
                "reason": "missing_strategy_asset",
                "execution_results": [],
                "rejected": [{"reasons": ["missing_strategy_asset"]}],
            }

        runtime_input = self.services.agent_gateway.build_runtime_inputs(
            trace_id=trace_id,
            market=context.market,
            policies=context.policies,
            forecasts=context.forecasts,
            news_events=context.news,
            latest_strategy=strategy_payload,
            macro_memory=context.macro_memory,
        )["risk_trader"]
        self.services.memory_assets.save_agent_session(
            agent_role="risk_trader",
            session_id=session_id,
            last_task_kind="execution",
        )
        try:
            envelope = self.services.agent_gateway.run_rt_submission(trace_id=trace_id, runtime_input=runtime_input)
        except SubmissionValidationError as exc:
            return self._handle_submission_validation_error(
                trace_id=trace_id,
                agent_role="risk_trader",
                session_id=session_id,
                task_kind="execution",
                error=exc,
            )
        submission = ExecutionSubmission.model_validate(envelope.payload)
        self.record_events(
            [
                self.services.agent_gateway.build_submission_event(trace_id=trace_id, envelope=envelope),
                EventFactory.build(
                    trace_id=trace_id,
                    event_type="execution.submitted",
                    source_module="agent_gateway",
                    entity_type="execution_batch",
                    entity_id=submission.decision_id,
                    payload={
                        "execution": submission.model_dump(mode="json"),
                        "envelope_id": envelope.envelope_id,
                    },
                ),
            ]
        )
        self.services.memory_assets.save_agent_session(
            agent_role="risk_trader",
            session_id=session_id,
            last_task_kind="execution",
            last_submission_kind="execution",
        )
        self.services.memory_assets.save_asset(
            asset_type="execution_batch",
            payload=submission.model_dump(mode="json"),
            trace_id=trace_id,
            actor_role="risk_trader",
            group_key=submission.decision_id,
            source_ref=envelope.envelope_id,
            metadata={"strategy_id": submission.strategy_id},
        )

        execution_contexts = self.services.agent_gateway.compile_execution_contexts(
            market=context.market,
            policies=context.policies,
            forecasts=context.forecasts,
            strategy_payload=strategy_payload,
        )
        context_by_symbol = {
            str(item.get("coin") or "").upper(): item
            for item in execution_contexts
            if isinstance(item, dict)
        }
        decisions: list[ExecutionDecision] = []
        for item in submission.decisions:
            payload = context_by_symbol.get(item.symbol, {})
            decisions.append(
                ExecutionDecision(
                    decision_id=submission.decision_id,
                    strategy_version=submission.strategy_id or "unknown",
                    context_id=str(payload.get("context_id") or new_id("execctx")),
                    product_id=str(payload.get("product_id") or f"{item.symbol}-PERP-INTX"),
                    coin=item.symbol,
                    action=item.action,
                    side=item.direction or ("flat" if item.action == "wait" else "long"),
                    size_pct_of_exposure_budget=item.size_pct_of_exposure_budget,
                    urgency=item.urgency,
                    valid_for_minutes=item.valid_for_minutes,
                    reason=item.reason,
                    priority=item.priority,
                )
            )

        authorization = self.services.policy_risk.authorize_execution(
            strategy_payload=strategy_payload,
            decisions=decisions,
            market=context.market,
            policies=context.policies,
        )
        self.record_events(self.services.policy_risk.build_execution_authorization_events(trace_id=trace_id, authorization=authorization))
        self.services.memory_assets.save_asset(
            asset_type="execution_authorization",
            payload=authorization.model_dump(mode="json"),
            trace_id=trace_id,
            actor_role="policy_risk",
            group_key=submission.decision_id,
            metadata={"strategy_id": submission.strategy_id},
        )

        accepted = [ExecutionDecision.model_validate(item) for item in authorization.accepted]
        live = bool(command.params.get("live")) and self.services.trade_execution.live_enabled
        max_notional = float(command.params["max_notional_usd"]) if live and command.params.get("max_notional_usd") is not None else None
        plans = self.services.trade_execution.build_execution_plans(
            decisions=accepted,
            total_equity_usd=context.market.portfolio.total_equity_usd,
            max_leverage=next(
                (
                    item.risk_limits.max_leverage
                    for item in context.policies.values()
                    if item.risk_limits.max_leverage
                ),
                1.0,
            ),
            max_notional_usd=max_notional,
        )
        self.record_events(self.services.trade_execution.build_plan_events(trace_id=trace_id, plans=plans))
        results = self.services.trade_execution.execute(plans, live=live)
        self.record_events(self.services.trade_execution.build_result_events(trace_id=trace_id, results=results))
        for result in results:
            self.services.memory_assets.save_asset(
                asset_type="execution_result",
                payload={"result_id": new_id("execution_result"), **result.model_dump(mode="json")},
                trace_id=trace_id,
                actor_role="risk_trader",
                group_key=submission.decision_id,
                metadata={"live": live},
            )

        return {
            "decision_id": submission.decision_id,
            "strategy_id": submission.strategy_id,
            "accepted_count": len(authorization.accepted),
            "rejected": authorization.rejected,
            "plan_count": len(plans),
            "execution_results": [item.model_dump(mode="json") for item in results],
            "live": live,
        }

    def _run_mea(self, *, trace_id: str, context: WorkflowRuntimeContext) -> dict[str, Any]:
        session_id = self.services.agent_gateway.session_id_for_role("macro_event_analyst")
        self.services.memory_assets.save_agent_session(
            agent_role="macro_event_analyst",
            session_id=session_id,
            last_task_kind="event_summary",
        )
        try:
            envelope = self.services.agent_gateway.run_mea_submission(
                trace_id=trace_id,
                runtime_input=context.agent_inputs["macro_event_analyst"],
            )
        except SubmissionValidationError as exc:
            return self._handle_submission_validation_error(
                trace_id=trace_id,
                agent_role="macro_event_analyst",
                session_id=session_id,
                task_kind="event_summary",
                error=exc,
            )
        submission = NewsSubmission.model_validate(envelope.payload)
        canonical_news = self.services.memory_assets.materialize_news_submission(
            trace_id=trace_id,
            authored_payload=submission.model_dump(mode="json"),
            actor_role="macro_event_analyst",
            source_ref=envelope.envelope_id,
        )
        self.record_events(
            [
                self.services.agent_gateway.build_submission_event(trace_id=trace_id, envelope=envelope),
                EventFactory.build(
                    trace_id=trace_id,
                    event_type="news.submitted",
                    source_module="agent_gateway",
                    entity_type="news_submission",
                    entity_id=str(canonical_news["submission_id"]),
                    payload={
                        "news": canonical_news,
                        "envelope_id": envelope.envelope_id,
                    },
                ),
            ]
        )
        self.services.memory_assets.save_agent_session(
            agent_role="macro_event_analyst",
            session_id=session_id,
            last_task_kind="event_summary",
            last_submission_kind="news",
        )
        for item in canonical_news["events"]:
            event_id = str(item["event_id"])
            self.services.memory_assets.save_asset(
                asset_type="macro_event",
                payload=item,
                trace_id=trace_id,
                actor_role="macro_event_analyst",
                group_key=event_id,
                source_ref=str(canonical_news["submission_id"]),
                asset_id=f"macro_event:{event_id}",
            )
        self.services.memory_assets.save_asset(
            asset_type="macro_daily_memory",
            payload={
                "memory_day_utc": new_id("memory_day"),
                "summary": "; ".join(str(event["summary"]) for event in canonical_news["events"]),
                "event_ids": [str(event["event_id"]) for event in canonical_news["events"]],
            },
            trace_id=trace_id,
            actor_role="macro_event_analyst",
            group_key="macro_daily_memory",
            source_ref=envelope.envelope_id,
        )

        return {
            "submission_id": canonical_news["submission_id"],
            "macro_event_count": len(canonical_news["events"]),
            "high_impact_count": len([item for item in canonical_news["events"] if item["impact_level"] == "high"]),
        }

    def _persist_market_snapshots(self, *, command_type: str, trace_id: str, market: Any) -> None:
        market_payload = market.model_dump(mode="json")
        captured_at_raw = None
        if market.market:
            first_snapshot = next(iter(market.market.values()))
            captured_at_raw = getattr(first_snapshot, "captured_at", None)
        captured_at = captured_at_raw if isinstance(captured_at_raw, datetime) else datetime.now(UTC)
        bucket_start = captured_at.replace(minute=(captured_at.minute // 15) * 15, second=0, microsecond=0)
        bucket_key = bucket_start.isoformat()
        latest_light = self.services.memory_assets.latest_asset(asset_type="market_light_snapshot")
        latest_bucket = ((latest_light or {}).get("metadata") or {}).get("bucket_start_utc")
        if latest_bucket != bucket_key:
            light_payload = {
                "bucket_start_utc": bucket_key,
                "portfolio": market.portfolio.model_dump(mode="json"),
                "market": {
                    coin: {
                        "product_id": snapshot.product_id,
                        "mark_price": snapshot.mark_price,
                        "spread_bps": snapshot.spread_bps,
                        "funding_rate": snapshot.funding_rate,
                        "premium": snapshot.premium,
                        "open_interest": snapshot.open_interest,
                        "day_notional_volume": snapshot.day_notional_volume,
                    }
                    for coin, snapshot in market.market.items()
                },
            }
            self.services.memory_assets.save_asset(
                asset_type="market_light_snapshot",
                payload=light_payload,
                trace_id=trace_id,
                actor_role="system",
                group_key=bucket_key,
                metadata={"bucket_start_utc": bucket_key},
            )
        self.services.memory_assets.save_asset(
            asset_type="market_key_snapshot",
            payload=market_payload,
            trace_id=trace_id,
            actor_role="system",
            group_key=trace_id,
            metadata={"reason": command_type},
        )
        self.services.memory_assets.save_asset(
            asset_type="portfolio_snapshot",
            payload=market.portfolio.model_dump(mode="json"),
            trace_id=trace_id,
            actor_role="system",
            group_key=trace_id,
            metadata={"reason": command_type},
        )

    def _handle_submission_validation_error(
        self,
        *,
        trace_id: str,
        agent_role: str,
        session_id: str,
        task_kind: str,
        error: SubmissionValidationError,
    ) -> dict[str, Any]:
        event = self.services.agent_gateway.build_submission_error_event(
            trace_id=trace_id,
            agent_role=agent_role,
            error=error,
        )
        self.record_events([event])
        self.services.memory_assets.save_agent_session(
            agent_role=agent_role,
            session_id=session_id,
            status="needs_revision",
            last_task_kind=task_kind,
        )
        self.services.memory_assets.save_asset(
            asset_type="submission_error",
            payload=event.payload,
            trace_id=trace_id,
            actor_role="system",
            group_key=agent_role,
            metadata={"task_kind": task_kind},
        )
        return {
            "degraded": True,
            "reason": "submission_validation_failed",
            "error_kind": error.error_kind,
            "schema_ref": error.schema_ref,
            "prompt_ref": error.prompt_ref,
            "errors": list(error.errors),
        }

    @staticmethod
    def _normalize_command(command_type: str) -> str:
        if command_type == "refresh_strategy":
            return "run_pm"
        if command_type == "rerun_trade_review":
            return "run_rt"
        return command_type

    @staticmethod
    def _resolve_pm_trigger_type(*, command: ManualTriggerCommand) -> str:
        raw = str(command.params.get("trigger_type") or "").strip()
        if raw:
            return raw
        return "manual"
