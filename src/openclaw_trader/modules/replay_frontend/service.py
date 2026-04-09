from __future__ import annotations

from ...config.models import SystemSettings
from ..state_memory.models import ReplayQueryView
from ..state_memory.service import StateMemoryService


class ReplayFrontendService:
    def __init__(self, state_memory: StateMemoryService, settings: SystemSettings | None = None) -> None:
        self.state_memory = state_memory
        self.settings = settings

    def query(self, *, trace_id: str | None = None, module: str | None = None) -> ReplayQueryView:
        return self.state_memory.query_replay(trace_id=trace_id, module=module)

    def overview(self) -> dict:
        overview = self.state_memory.build_overview().model_dump(mode="json")
        if overview.get("risk_overlay") is None:
            fallback = self._fallback_risk_overlay(overview)
            if fallback is not None:
                overview["risk_overlay"] = fallback
        return overview

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

    def _fallback_risk_overlay(self, overview: dict) -> dict | None:
        if self.settings is None:
            return None
        latest_portfolio = overview.get("latest_portfolio") or {}
        if not isinstance(latest_portfolio, dict):
            return None
        payload = latest_portfolio.get("payload") or {}
        if not isinstance(payload, dict):
            return None
        current_equity = self._to_float(payload.get("total_equity_usd"))
        if current_equity is None or current_equity <= 0:
            return None

        current_day = None
        captured_at = payload.get("captured_at")
        if isinstance(captured_at, str) and captured_at:
            current_day = captured_at[:10]

        history = overview.get("portfolio_history") or []
        history_peaks: list[float] = []
        if isinstance(history, list):
            for item in history:
                if not isinstance(item, dict):
                    continue
                created_at = item.get("created_at")
                if current_day and isinstance(created_at, str) and not created_at.startswith(current_day):
                    continue
                total_equity = self._to_float(item.get("total_equity_usd"))
                if total_equity is not None and total_equity > 0:
                    history_peaks.append(total_equity)

        starting_equity = self._to_float(payload.get("starting_equity_usd"))
        day_peak = max(
            [current_equity, *(history_peaks or []), *([starting_equity] if starting_equity is not None else [])]
        )
        if day_peak <= 0:
            return None

        def line(drawdown_pct: float) -> dict[str, object]:
            return {
                "drawdown_pct": round(drawdown_pct, 4),
                "equity_usd": str(round(day_peak * (1.0 - drawdown_pct / 100.0), 8)),
            }

        return {
            "state": "fallback",
            "day_peak_equity_usd": str(round(day_peak, 8)),
            "current_equity_usd": str(round(current_equity, 8)),
            "observe": line(float(self.settings.risk.portfolio_peak_observe_drawdown_pct)),
            "reduce": line(float(self.settings.risk.portfolio_peak_reduce_drawdown_pct)),
            "exit": line(float(self.settings.risk.portfolio_peak_exit_drawdown_pct)),
        }

    @staticmethod
    def _to_float(value: object) -> float | None:
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return number if number == number else None
