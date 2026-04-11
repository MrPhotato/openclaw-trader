from __future__ import annotations

from ....shared.utils import new_id
from ..models import ReplayQueryView, StateSnapshot
from .events import EventRepository
from .portfolio import PortfolioRepository
from .strategies import StrategyRepository
from .workflows import WorkflowRepository


class ReplayRepository:
    def __init__(
        self,
        *,
        workflows: WorkflowRepository,
        events: EventRepository,
        strategies: StrategyRepository,
        portfolio: PortfolioRepository,
    ) -> None:
        self.workflows = workflows
        self.events = events
        self.strategies = strategies
        self.portfolio = portfolio

    def capture_snapshot(self, trace_id: str) -> StateSnapshot:
        workflow = self.workflows.get(trace_id)
        portfolio = self.portfolio.latest()
        strategy = self.strategies.latest()
        return StateSnapshot(
            snapshot_id=new_id("snapshot"),
            trace_id=trace_id,
            workflow_state=workflow,
            portfolio_state=portfolio["payload"] if portfolio else None,
            strategy_ref=strategy["strategy_version"] if strategy else None,
        )

    def query(self, *, trace_id: str | None = None, module: str | None = None) -> ReplayQueryView:
        events = self.events.query(trace_id=trace_id, module=module, limit=1000)
        states: list[dict] = []
        if trace_id:
            workflow = self.workflows.get(trace_id)
            if workflow is not None:
                states.append(workflow.model_dump(mode="json"))
        return ReplayQueryView(
            trace_id=trace_id,
            time_window={},
            events=events,
            states=states,
            render_hints={"mode": "timeline"},
        )
