from __future__ import annotations

from datetime import UTC, datetime

from ...shared.protocols import EventEnvelope, EventFactory
from ...shared.utils import new_id
from .events import EVENT_NOTIFICATION_RECORDED, EVENT_PARAMETER_CHANGED, EVENT_STATE_SNAPSHOT_CAPTURED, MODULE_NAME
from .models import (
    AgentSessionState,
    NewsSubmissionAsset,
    NotificationResult,
    OverviewQueryView,
    ReplayQueryView,
    StateSnapshot,
    StrategyAsset,
    WorkflowStateRef,
)
from .repository import StateMemoryRepository


class StateMemoryService:
    def __init__(self, repository: StateMemoryRepository) -> None:
        self.repository = repository

    def save_workflow(self, command_id: str, workflow: WorkflowStateRef, payload: dict) -> None:
        self.repository.save_workflow(command_id, workflow, payload)

    def get_workflow_by_command(self, command_id: str) -> WorkflowStateRef | None:
        return self.repository.get_workflow_by_command(command_id)

    def get_workflow(self, trace_id: str) -> WorkflowStateRef | None:
        return self.repository.get_workflow(trace_id)

    def append_event(self, envelope: EventEnvelope) -> None:
        self.repository.append_event(envelope)

    def query_events(self, *, trace_id: str | None = None, module: str | None = None, limit: int = 200) -> list[dict]:
        return self.repository.query_events(trace_id=trace_id, module=module, limit=limit)

    def save_strategy(self, strategy_version: str, trace_id: str, payload: dict) -> None:
        self.repository.save_strategy(strategy_version, trace_id, payload)

    def materialize_strategy_asset(
        self,
        *,
        trace_id: str,
        authored_payload: dict,
        trigger_type: str,
        actor_role: str = "pm",
        source_ref: str | None = None,
    ) -> dict:
        now = datetime.now(UTC)
        previous_strategy = self.latest_strategy()
        previous_payload = previous_strategy["payload"] if previous_strategy else {}
        previous_id = str(previous_payload.get("strategy_id") or "").strip() or None
        previous_revision = previous_payload.get("revision_number") if isinstance(previous_payload, dict) else None
        try:
            previous_revision_number = int(previous_revision)
        except (TypeError, ValueError):
            previous_revision_number = 0

        canonical_payload = dict(authored_payload)
        canonical_payload.update(
            {
                "strategy_id": new_id("strategy"),
                "strategy_day_utc": now.date().isoformat(),
                "generated_at_utc": now.isoformat(),
                "trigger_type": trigger_type,
                "supersedes_strategy_id": previous_id,
                "revision_number": previous_revision_number + 1 if previous_id else 1,
            }
        )
        canonical_payload = StrategyAsset.model_validate(canonical_payload).model_dump(mode="json")
        self.save_asset(
            asset_type="strategy",
            payload=canonical_payload,
            trace_id=trace_id,
            actor_role=actor_role,
            group_key=str(canonical_payload["strategy_day_utc"]),
            source_ref=source_ref,
            metadata={"trigger_type": trigger_type},
        )
        self.save_strategy(str(canonical_payload["strategy_id"]), trace_id, canonical_payload)
        return canonical_payload

    def materialize_news_submission(
        self,
        *,
        trace_id: str,
        authored_payload: dict,
        actor_role: str = "macro_event_analyst",
        source_ref: str | None = None,
    ) -> dict:
        now = datetime.now(UTC)
        canonical_payload = dict(authored_payload)
        canonical_payload.update(
            {
                "submission_id": new_id("news"),
                "generated_at_utc": now.isoformat(),
            }
        )
        canonical_payload = NewsSubmissionAsset.model_validate(canonical_payload).model_dump(mode="json")
        self.save_asset(
            asset_type="news_submission",
            payload=canonical_payload,
            trace_id=trace_id,
            actor_role=actor_role,
            group_key=str(canonical_payload["submission_id"]),
            source_ref=source_ref,
        )
        return canonical_payload

    def latest_strategy(self) -> dict | None:
        return self.repository.latest_strategy()

    def get_latest_strategy(self) -> dict | None:
        latest_asset = self.latest_asset(asset_type="strategy")
        if latest_asset is not None:
            return latest_asset
        return self.latest_strategy()

    def save_portfolio(self, trace_id: str, payload: dict) -> None:
        self.repository.save_portfolio(trace_id, payload)

    def latest_portfolio(self) -> dict | None:
        return self.repository.latest_portfolio()

    def recent_portfolios(self, *, limit: int = 24) -> list[dict]:
        return self.repository.recent_portfolios(limit=limit)

    def save_asset(
        self,
        *,
        asset_type: str,
        payload: dict,
        trace_id: str | None = None,
        actor_role: str | None = None,
        group_key: str | None = None,
        source_ref: str | None = None,
        metadata: dict | None = None,
        asset_id: str | None = None,
    ) -> dict:
        record_id = asset_id or new_id(asset_type.replace(".", "_"))
        record = {
            "asset_id": record_id,
            "asset_type": asset_type,
            "trace_id": trace_id,
            "actor_role": actor_role,
            "group_key": group_key,
            "source_ref": source_ref,
            "payload": payload,
            "metadata": metadata or {},
            "created_at": datetime.now(UTC).isoformat(),
        }
        self.repository.save_asset(
            asset_id=record_id,
            asset_type=asset_type,
            trace_id=trace_id,
            actor_role=actor_role,
            group_key=group_key,
            source_ref=source_ref,
            payload=payload,
            metadata=metadata or {},
        )
        return record

    def get_asset(self, asset_id: str) -> dict | None:
        return self.repository.get_asset(asset_id)

    def latest_asset(self, *, asset_type: str, actor_role: str | None = None) -> dict | None:
        return self.repository.latest_asset(asset_type=asset_type, actor_role=actor_role)

    def recent_assets(
        self,
        *,
        asset_type: str | None = None,
        actor_role: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        return self.repository.recent_assets(asset_type=asset_type, actor_role=actor_role, limit=limit)

    def get_pending_scheduled_rechecks(self) -> list[dict]:
        latest_strategy = self.get_latest_strategy()
        if latest_strategy is None:
            return []
        payload = latest_strategy.get("payload") or {}
        rechecks = list(payload.get("scheduled_rechecks") or [])
        now = datetime.now(UTC)
        pending: list[dict] = []
        for item in rechecks:
            if not isinstance(item, dict):
                continue
            raw = item.get("recheck_at_utc")
            try:
                recheck_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except Exception:
                recheck_at = None
            if recheck_at is None or recheck_at >= now:
                pending.append(dict(item))
        return pending

    def get_macro_memory(self, *, limit: int = 5) -> list[dict]:
        macro_daily = self.recent_assets(asset_type="macro_daily_memory", limit=limit)
        if macro_daily:
            return [item["payload"] for item in macro_daily]
        return [item["payload"] for item in self.recent_assets(asset_type="macro_event", limit=max(limit, 10))]

    def get_recent_execution_results(self, *, limit: int = 10) -> list[dict]:
        return [item["payload"] for item in self.recent_assets(asset_type="execution_result", limit=limit)]

    def get_recent_news_submissions(self, *, limit: int = 10) -> list[dict]:
        return [item["payload"] for item in self.recent_assets(asset_type="news_submission", limit=limit)]

    def save_agent_session(
        self,
        *,
        agent_role: str,
        session_id: str,
        status: str = "active",
        last_task_kind: str | None = None,
        last_submission_kind: str | None = None,
        last_reset_command: str | None = None,
    ) -> AgentSessionState:
        state = AgentSessionState(
            agent_role=agent_role,
            session_id=session_id,
            status=status,
            last_task_kind=last_task_kind,
            last_submission_kind=last_submission_kind,
            last_reset_command=last_reset_command,
        )
        self.repository.save_agent_session(state)
        return state

    def get_agent_session(self, agent_role: str) -> AgentSessionState | None:
        return self.repository.get_agent_session(agent_role)

    def list_agent_sessions(self) -> list[dict]:
        return self.repository.list_agent_sessions()

    def save_notification_result(self, result: NotificationResult, payload: dict) -> EventEnvelope:
        self.repository.save_notification_result(result, payload)
        self.save_asset(
            asset_type="notification_result",
            payload={
                "notification_id": result.notification_id,
                "delivered": result.delivered,
                "provider_message_id": result.provider_message_id,
                "failure_reason": result.failure_reason,
                "delivered_at": result.delivered_at.isoformat(),
                "command": payload,
            },
            trace_id=payload.get("trace_id"),
            actor_role="system",
            group_key=result.notification_id,
        )
        event = EventFactory.build(
            trace_id=payload.get("trace_id", "notification"),
            event_type=EVENT_NOTIFICATION_RECORDED,
            source_module=MODULE_NAME,
            entity_type="notification_result",
            entity_id=result.notification_id,
            payload={"result": result.model_dump(mode="json"), "command": payload},
        )
        self.append_event(event)
        return event

    def list_parameters(self) -> list[dict]:
        return self.repository.list_parameters()

    def save_parameter(self, name: str, scope: str, value: dict, *, operator: str, reason: str) -> EventEnvelope:
        self.repository.save_parameter(name, scope, value, operator=operator, reason=reason)
        event = EventFactory.build(
            trace_id="parameters",
            event_type=EVENT_PARAMETER_CHANGED,
            source_module=MODULE_NAME,
            entity_type="parameter",
            entity_id=f"{scope}:{name}",
            payload={
                "name": name,
                "scope": scope,
                "value": value,
                "operator": operator,
                "reason": reason,
            },
        )
        self.append_event(event)
        return event

    def capture_snapshot(self, trace_id: str) -> tuple[StateSnapshot, EventEnvelope]:
        snapshot = self.repository.capture_snapshot(trace_id)
        event = EventFactory.build(
            trace_id=trace_id,
            event_type=EVENT_STATE_SNAPSHOT_CAPTURED,
            source_module=MODULE_NAME,
            entity_type="state_snapshot",
            entity_id=snapshot.snapshot_id,
            payload=snapshot.model_dump(mode="json"),
        )
        self.append_event(event)
        return snapshot, event

    def query_replay(self, *, trace_id: str | None = None, module: str | None = None) -> ReplayQueryView:
        return self.repository.query_replay(trace_id=trace_id, module=module)

    def ensure_bootstrap_parameter(self, name: str, scope: str, value: dict, *, operator: str, reason: str) -> None:
        existing = {f"{row['scope']}:{row['name']}" for row in self.list_parameters()}
        if f"{scope}:{name}" not in existing:
            self.save_parameter(name, scope, value, operator=operator, reason=reason)

    def build_overview(self) -> OverviewQueryView:
        latest_strategy = self.latest_asset(asset_type="strategy")
        latest_portfolio = self.latest_asset(asset_type="portfolio_snapshot") or self.latest_portfolio()
        latest_execution_batch = self.latest_asset(asset_type="execution_batch")
        recent_execution_results = self.recent_assets(asset_type="execution_result", limit=10)
        current_macro_events = self.recent_assets(asset_type="macro_event", limit=10)
        recent_notifications = self.recent_assets(asset_type="notification_result", limit=10)
        portfolio_history = [
            {
                "created_at": item["created_at"],
                "total_equity_usd": item.get("payload", {}).get("total_equity_usd"),
            }
            for item in self.recent_portfolios(limit=1000)
        ]
        return OverviewQueryView(
            system={
                "strategy_present": latest_strategy is not None,
                "execution_present": latest_execution_batch is not None,
                "macro_event_count": len(current_macro_events),
                "updated_at": datetime.now(UTC).isoformat(),
            },
            latest_strategy=latest_strategy,
            latest_portfolio=latest_portfolio,
            portfolio_history=portfolio_history,
            latest_execution_batch=latest_execution_batch,
            recent_execution_results=recent_execution_results,
            current_macro_events=current_macro_events,
            agent_sessions=self.list_agent_sessions(),
            recent_notifications=recent_notifications,
            recent_events=self.query_events(limit=25),
        )
