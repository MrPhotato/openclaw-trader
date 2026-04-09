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
        latest_asset = self._latest_agent_asset(agent_role)
        recent_assets = self.state_memory.recent_assets(actor_role=agent_role, limit=10)
        response = {
            "session": self.state_memory.get_agent_session(agent_role).model_dump(mode="json")
            if self.state_memory.get_agent_session(agent_role)
            else None,
            "latest_asset": latest_asset,
            "recent_assets": recent_assets,
        }
        if agent_role == "pm":
            response["latest_strategy"] = self.state_memory.latest_asset(asset_type="strategy", actor_role="pm") or self.state_memory.latest_asset(asset_type="strategy")
        elif agent_role == "risk_trader":
            response["latest_execution_batch"] = self.state_memory.latest_asset(asset_type="execution_batch", actor_role="risk_trader")
            response["latest_rt_trigger_event"] = self.state_memory.latest_asset(asset_type="rt_trigger_event", actor_role="system")
            response["latest_risk_brake_event"] = self.state_memory.latest_asset(asset_type="risk_brake_event", actor_role="system")
            response["recent_execution_thoughts"] = self.state_memory.get_recent_execution_thoughts(limit=6)
            response["latest_rt_tactical_map"] = self.state_memory.latest_asset(asset_type="rt_tactical_map", actor_role="risk_trader")
            response["tactical_brief"] = self._build_rt_tactical_brief(
                latest_strategy=self.state_memory.latest_asset(asset_type="strategy") or self.state_memory.latest_strategy(),
                latest_execution_batch=response["latest_execution_batch"],
                latest_rt_tactical_map=response["latest_rt_tactical_map"],
                latest_rt_trigger_event=response["latest_rt_trigger_event"],
                latest_risk_brake_event=response["latest_risk_brake_event"],
                recent_execution_thoughts=response["recent_execution_thoughts"],
            )
        elif agent_role == "macro_event_analyst":
            response["latest_macro_daily_memory"] = self.state_memory.latest_asset(asset_type="macro_daily_memory", actor_role="macro_event_analyst") or self.state_memory.latest_asset(asset_type="macro_daily_memory")
            response["recent_macro_events"] = self.state_memory.recent_assets(asset_type="macro_event", actor_role="macro_event_analyst", limit=8) or self.state_memory.recent_assets(asset_type="macro_event", limit=8)
        elif agent_role == "crypto_chief":
            response["latest_chief_retro"] = self.state_memory.latest_asset(asset_type="chief_retro", actor_role="crypto_chief")
            response["recent_notifications"] = self.state_memory.recent_assets(asset_type="notification_result", limit=6)
        return response

    def _latest_agent_asset(self, agent_role: str) -> dict | None:
        if agent_role == "pm":
            return self.state_memory.latest_asset(asset_type="strategy", actor_role=agent_role) or self.state_memory.latest_asset(asset_type="strategy")
        if agent_role == "risk_trader":
            return self.state_memory.latest_asset(asset_type="execution_batch", actor_role=agent_role) or self.state_memory.latest_asset(asset_type="execution_result", actor_role=agent_role)
        if agent_role == "macro_event_analyst":
            return self.state_memory.latest_asset(asset_type="macro_daily_memory", actor_role=agent_role) or self.state_memory.latest_asset(asset_type="macro_event", actor_role=agent_role)
        if agent_role == "crypto_chief":
            return self.state_memory.latest_asset(asset_type="chief_retro", actor_role=agent_role)
        return None

    def _build_rt_tactical_brief(
        self,
        *,
        latest_strategy: dict | None,
        latest_execution_batch: dict | None,
        latest_rt_tactical_map: dict | None,
        latest_rt_trigger_event: dict | None,
        latest_risk_brake_event: dict | None,
        recent_execution_thoughts: list[dict] | None,
    ) -> dict | None:
        if latest_rt_tactical_map:
            payload = dict(latest_rt_tactical_map.get("payload") or {})
            return {
                "state": "materialized_map",
                "updated_at": payload.get("updated_at_utc") or latest_rt_tactical_map.get("created_at"),
                "portfolio_posture": payload.get("portfolio_posture"),
                "desk_focus": payload.get("desk_focus"),
                "risk_bias": payload.get("risk_bias"),
                "next_review_hint": payload.get("next_review_hint"),
                "map_refresh_reason": payload.get("map_refresh_reason"),
                "coins": list(payload.get("coins") or []),
                "trigger": self._compact_rt_trigger(latest_rt_trigger_event, latest_risk_brake_event),
            }

        strategy_payload = dict((latest_strategy or {}).get("payload") or latest_strategy or {})
        batch_payload = dict((latest_execution_batch or {}).get("payload") or {})
        recent_thoughts = [dict(item) for item in list(recent_execution_thoughts or []) if isinstance(item, dict)]
        decisions = [dict(item) for item in list(batch_payload.get("decisions") or []) if isinstance(item, dict)]
        if not strategy_payload and not decisions and not recent_thoughts:
            return None

        targets_by_symbol = {
            str(item.get("symbol") or "").strip().upper(): dict(item)
            for item in list(strategy_payload.get("targets") or [])
            if isinstance(item, dict) and str(item.get("symbol") or "").strip()
        }
        thoughts_by_symbol = {
            str(item.get("symbol") or "").strip().upper(): dict(item)
            for item in recent_thoughts
            if str(item.get("symbol") or "").strip()
        }
        decisions_by_symbol = {
            str(item.get("symbol") or "").strip().upper(): dict(item)
            for item in decisions
            if str(item.get("symbol") or "").strip()
        }
        symbols = list(dict.fromkeys([*decisions_by_symbol.keys(), *thoughts_by_symbol.keys(), *targets_by_symbol.keys()]))[:4]

        coins: list[dict[str, object]] = []
        for symbol in symbols:
            decision = decisions_by_symbol.get(symbol, {})
            thought = thoughts_by_symbol.get(symbol, {})
            target = targets_by_symbol.get(symbol, {})
            exposure_band = list(target.get("target_exposure_band_pct") or [])
            band_text = ""
            if exposure_band:
                band_text = f"目标敞口 {exposure_band[0]}% - {exposure_band[-1]}%"
            reason = str(thought.get("reason") or decision.get("reason") or "").strip()
            take_profit = str(
                thought.get("reference_take_profit_condition")
                or decision.get("reference_take_profit_condition")
                or ""
            ).strip()
            stop_loss = str(
                thought.get("reference_stop_loss_condition")
                or decision.get("reference_stop_loss_condition")
                or ""
            ).strip()
            risk_lock = self._risk_lock_text(latest_risk_brake_event)
            coins.append(
                {
                    "coin": symbol,
                    "working_posture": self._rt_posture_text(decision=decision, target=target),
                    "base_case": reason or band_text or "当前还没有可展示的本轮判断文本。",
                    "preferred_add_condition": band_text or "等待更清晰的结构性确认后再加风险。",
                    "preferred_reduce_condition": stop_loss or risk_lock or "若波动走坏或风控收紧，优先减仓。",
                    "reference_take_profit_condition": take_profit or "暂无单独记录的止盈参考。",
                    "reference_stop_loss_condition": stop_loss or "暂无单独记录的止损参考。",
                    "no_trade_zone": risk_lock or "没有额外记录的禁做区间。",
                    "force_pm_recheck_condition": str(strategy_payload.get("portfolio_invalidation") or "当组合主逻辑被证伪时，要求 PM 复核。"),
                    "next_focus": str(target.get("state") or decision.get("urgency") or "继续观察结构与成交反馈。"),
                }
            )

        return {
            "state": "derived_brief",
            "updated_at": batch_payload.get("generated_at_utc") or (latest_execution_batch or {}).get("created_at"),
            "portfolio_posture": self._portfolio_posture_text(strategy_payload),
            "desk_focus": self._desk_focus_text(latest_rt_trigger_event, decisions_by_symbol),
            "risk_bias": self._risk_bias_text(latest_risk_brake_event),
            "next_review_hint": self._next_review_hint_text(strategy_payload),
            "map_refresh_reason": str((latest_rt_trigger_event or {}).get("payload", {}).get("summary") or "最近一次执行节奏与风险状态已提炼成公开摘要。"),
            "coins": coins,
            "trigger": self._compact_rt_trigger(latest_rt_trigger_event, latest_risk_brake_event),
        }

    @staticmethod
    def _compact_rt_trigger(latest_rt_trigger_event: dict | None, latest_risk_brake_event: dict | None) -> dict[str, object] | None:
        trigger_payload = dict((latest_rt_trigger_event or {}).get("payload") or {})
        risk_payload = dict((latest_risk_brake_event or {}).get("payload") or {})
        if not trigger_payload and not risk_payload:
            return None
        return {
            "reason": trigger_payload.get("reason") or risk_payload.get("reason"),
            "severity": trigger_payload.get("severity") or risk_payload.get("severity"),
            "coins": list(trigger_payload.get("coins") or risk_payload.get("coins") or []),
            "lock_mode": risk_payload.get("lock_mode"),
            "scope": risk_payload.get("scope"),
        }

    @staticmethod
    def _portfolio_posture_text(strategy_payload: dict) -> str:
        mode = str(strategy_payload.get("portfolio_mode") or "").strip().lower()
        if mode == "aggressive":
            return "主动进攻"
        if mode == "defensive":
            return "偏防守"
        if mode == "normal":
            return "常规推进"
        return "等待明确组合姿态"

    @staticmethod
    def _desk_focus_text(latest_rt_trigger_event: dict | None, decisions_by_symbol: dict[str, dict]) -> str:
        trigger_payload = dict((latest_rt_trigger_event or {}).get("payload") or {})
        coins = [coin for coin in list(trigger_payload.get("coins") or []) if coin]
        if coins:
            return f"本轮优先关注 {' / '.join(str(coin).upper() for coin in coins[:3])}。"
        if decisions_by_symbol:
            return f"本轮执行重点落在 {' / '.join(list(decisions_by_symbol.keys())[:3])}。"
        return "先看触发原因，再决定是否进入执行。"

    @staticmethod
    def _risk_bias_text(latest_risk_brake_event: dict | None) -> str:
        payload = dict((latest_risk_brake_event or {}).get("payload") or {})
        lock_mode = str(payload.get("lock_mode") or "").strip().lower()
        if lock_mode == "flat_only":
            return "只允许平仓，避免新增风险"
        if lock_mode == "reduce_only":
            return "只允许减仓，风险偏防守"
        if payload:
            return "风险护栏正在生效"
        return "风险状态正常，可按策略节奏推进"

    @staticmethod
    def _next_review_hint_text(strategy_payload: dict) -> str:
        rechecks = [dict(item) for item in list(strategy_payload.get("scheduled_rechecks") or []) if isinstance(item, dict)]
        if rechecks:
            first = rechecks[0]
            if first.get("recheck_at_utc"):
                return f"下一次复核：{first['recheck_at_utc']}"
        return "下一轮由 RT cadence 或风险事件唤醒。"

    @staticmethod
    def _rt_posture_text(*, decision: dict, target: dict) -> str:
        action = str(decision.get("action") or "").strip().lower()
        direction = str(decision.get("direction") or target.get("direction") or "").strip().lower()
        if action == "add":
            return "逢确认加仓" if direction == "long" else "逢确认加空"
        if action in {"reduce", "close"}:
            return "优先减仓兑现" if direction == "long" else "优先回补空单"
        if action == "hold":
            return "继续持仓观察"
        if direction == "long":
            return "偏多观察"
        if direction == "short":
            return "偏空观察"
        return "暂不主动交易"

    @staticmethod
    def _risk_lock_text(latest_risk_brake_event: dict | None) -> str:
        payload = dict((latest_risk_brake_event or {}).get("payload") or {})
        lock_mode = str(payload.get("lock_mode") or "").strip().lower()
        if lock_mode == "flat_only":
            return "当前风险锁要求只允许平仓。"
        if lock_mode == "reduce_only":
            return "当前风险锁要求只允许减仓。"
        return ""

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
