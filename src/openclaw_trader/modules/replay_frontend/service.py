from __future__ import annotations

from ..state_memory.models import ReplayQueryView
from ..state_memory.service import StateMemoryService


class ReplayFrontendService:
    def __init__(self, state_memory: StateMemoryService) -> None:
        self.state_memory = state_memory

    def query(self, *, trace_id: str | None = None, module: str | None = None) -> ReplayQueryView:
        return self.state_memory.query_replay(trace_id=trace_id, module=module)

    def overview(self) -> dict:
        return self.state_memory.build_overview().model_dump(mode="json")

    def current_news(self) -> dict:
        return {
            "latest_batch": self.state_memory.latest_asset(asset_type="news_batch"),
            "macro_events": self.state_memory.recent_assets(asset_type="macro_event", limit=20),
            "macro_daily_memory": self.state_memory.latest_asset(asset_type="macro_daily_memory"),
        }

    def recent_executions(self) -> dict:
        return {
            "latest_execution_batch": self.state_memory.latest_asset(asset_type="execution_batch"),
            "results": self.state_memory.recent_assets(asset_type="execution_result", limit=20),
        }

    def latest_agent_state(self, agent_role: str) -> dict:
        return {
            "session": self.state_memory.get_agent_session(agent_role).model_dump(mode="json")
            if self.state_memory.get_agent_session(agent_role)
            else None,
            "latest_asset": self.state_memory.latest_asset(asset_type="strategy", actor_role=agent_role)
            or self.state_memory.latest_asset(asset_type="execution_batch", actor_role=agent_role)
            or self.state_memory.latest_asset(asset_type="macro_daily_memory", actor_role=agent_role),
            "recent_assets": self.state_memory.recent_assets(actor_role=agent_role, limit=10),
        }

    def build_daily_report(self) -> dict:
        latest_strategy = self.state_memory.latest_asset(asset_type="strategy") or self.state_memory.latest_strategy()
        latest_portfolio = self.state_memory.latest_asset(asset_type="portfolio_snapshot") or self.state_memory.latest_portfolio()
        return {
            "overview": self.overview(),
            "strategy": latest_strategy,
            "portfolio": latest_portfolio,
            "events": self.state_memory.query_events(limit=20),
        }
