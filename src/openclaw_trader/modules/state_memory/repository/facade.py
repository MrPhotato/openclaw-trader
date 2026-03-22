from __future__ import annotations

from ....shared.infra import SqliteDatabase
from ....shared.protocols import EventEnvelope
from ..models import AgentSessionState, NotificationResult, ReplayQueryView, StateSnapshot, WorkflowStateRef
from .assets import AssetRepository
from .events import EventRepository
from .notifications import NotificationRepository
from .parameters import ParameterRepository
from .portfolio import PortfolioRepository
from .replay import ReplayRepository
from .schema import initialize_state_memory_schema
from .sessions import AgentSessionRepository
from .strategies import StrategyRepository
from .workflows import WorkflowRepository


class StateMemoryRepository:
    def __init__(self, database: SqliteDatabase) -> None:
        self.database = database
        initialize_state_memory_schema(database)
        self.workflows = WorkflowRepository(database)
        self.events = EventRepository(database)
        self.strategies = StrategyRepository(database)
        self.portfolio = PortfolioRepository(database)
        self.notifications = NotificationRepository(database)
        self.assets = AssetRepository(database)
        self.sessions = AgentSessionRepository(database)
        self.parameters = ParameterRepository(database)
        self.replay = ReplayRepository(
            workflows=self.workflows,
            events=self.events,
            strategies=self.strategies,
            portfolio=self.portfolio,
        )

    def save_workflow(self, command_id: str, workflow: WorkflowStateRef, payload: dict) -> None:
        self.workflows.save(command_id, workflow, payload)

    def get_workflow_by_command(self, command_id: str) -> WorkflowStateRef | None:
        return self.workflows.get_by_command(command_id)

    def get_workflow(self, trace_id: str) -> WorkflowStateRef | None:
        return self.workflows.get(trace_id)

    def append_event(self, envelope: EventEnvelope) -> None:
        self.events.append(envelope)

    def query_events(self, *, trace_id: str | None = None, module: str | None = None, limit: int = 200) -> list[dict]:
        return self.events.query(trace_id=trace_id, module=module, limit=limit)

    def save_strategy(self, strategy_version: str, trace_id: str, payload: dict) -> None:
        self.strategies.save(strategy_version, trace_id, payload)

    def latest_strategy(self) -> dict | None:
        return self.strategies.latest()

    def save_portfolio(self, trace_id: str, payload: dict) -> None:
        self.portfolio.save(trace_id, payload)

    def latest_portfolio(self) -> dict | None:
        return self.portfolio.latest()

    def recent_portfolios(self, *, limit: int = 24) -> list[dict]:
        return self.portfolio.recent(limit=limit)

    def save_notification_result(self, result: NotificationResult, payload: dict) -> None:
        self.notifications.save_result(result, payload)

    def save_asset(
        self,
        *,
        asset_id: str,
        asset_type: str,
        trace_id: str | None,
        actor_role: str | None,
        group_key: str | None,
        source_ref: str | None,
        payload: dict,
        metadata: dict,
    ) -> None:
        self.assets.save(
            asset_id=asset_id,
            asset_type=asset_type,
            trace_id=trace_id,
            actor_role=actor_role,
            group_key=group_key,
            source_ref=source_ref,
            payload=payload,
            metadata=metadata,
        )

    def get_asset(self, asset_id: str) -> dict | None:
        return self.assets.get(asset_id)

    def latest_asset(self, *, asset_type: str, actor_role: str | None = None) -> dict | None:
        return self.assets.latest(asset_type=asset_type, actor_role=actor_role)

    def recent_assets(
        self,
        *,
        asset_type: str | None = None,
        actor_role: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        return self.assets.recent(asset_type=asset_type, actor_role=actor_role, limit=limit)

    def save_agent_session(self, state: AgentSessionState) -> None:
        self.sessions.save(state)

    def get_agent_session(self, agent_role: str) -> AgentSessionState | None:
        return self.sessions.get(agent_role)

    def list_agent_sessions(self) -> list[dict]:
        return self.sessions.list()

    def list_parameters(self) -> list[dict]:
        return self.parameters.list()

    def save_parameter(self, name: str, scope: str, value: dict, *, operator: str, reason: str) -> None:
        self.parameters.save(name, scope, value, operator=operator, reason=reason)

    def capture_snapshot(self, trace_id: str) -> StateSnapshot:
        return self.replay.capture_snapshot(trace_id)

    def query_replay(self, *, trace_id: str | None = None, module: str | None = None) -> ReplayQueryView:
        return self.replay.query(trace_id=trace_id, module=module)
