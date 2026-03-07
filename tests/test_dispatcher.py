from __future__ import annotations

import json
import io
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
import subprocess

import openclaw_trader.dispatch as dispatch_module
from openclaw_trader.config import (
    AppConfig,
    DispatchConfig,
    NewsConfig,
    PerpConfig,
    RiskConfig,
    RuntimeConfig,
    StrategyConfig,
    WorkflowConfig,
)
from openclaw_trader.dispatch import DAILY_STRATEGY_SLOT_LOCK_PREFIX, OpenClawAgentRunner, TriggerDispatcher, run_strategy_refresh
from openclaw_trader.dispatch.notifications import format_trade_event_message, should_emit_trade_event
from openclaw_trader.models import (
    AutopilotDecision,
    AutopilotPhase,
    EmergencyExitDecision,
    EntryWorkflowMode,
    LlmTradeReviewDecision,
    LlmTradeReviewOrderDecision,
    PerpPaperPortfolio,
    RiskEvaluation,
    RiskProfile,
    SignalDecision,
    SignalSide,
    NewsItem,
)
from openclaw_trader.state import StateStore


class _FakeRunner(OpenClawAgentRunner):
    def __init__(self, runtime: RuntimeConfig):
        super().__init__(runtime)
        self.calls: list[tuple[str, bool]] = []
        self.sent_texts: list[str] = []

    def run(self, action, *, now=None):  # type: ignore[override]
        self.calls.append((action.kind, action.deliver))
        return {"success": True, "returncode": 0, "stdout": "{}", "stderr": "", "payload": {}}

    def send_text(self, message: str):  # type: ignore[override]
        self.sent_texts.append(message)
        return {"success": True, "returncode": 0, "stdout": "", "stderr": "", "payload": {}, "text": message}


class _TradeReviewRunner(_FakeRunner):
    def run(self, action, *, now=None):  # type: ignore[override]
        self.calls.append((action.kind, action.deliver))
        text = "{}"
        if action.kind == "strategy":
            text = '{"strategy_date":"2026-03-03","market_regime":"trend","risk_mode":"normal","summary":"ok","invalidators":[],"symbols":[{"symbol":"BTC-PERP","bias":"short","max_position_share_pct":20,"max_order_share_pct":8,"thesis":"ok"}]}'
        elif action.kind == "trade_review":
            text = '{"decision":"approve","reason":"先处理全组合候选","orders":[{"product_id":"BTC-PERP","decision":"approve","size_scale":0.5,"reason":"BTC 轻量开仓","stop_loss_price":"91000","take_profit_price":"84000","exit_plan":"若反弹失效则尽快回补"},{"product_id":"ETH-PERP","decision":"approve","size_scale":0.25,"reason":"ETH 进一步缩量","stop_loss_price":"2400","take_profit_price":"2100","exit_plan":"若弱势延续则持有，否则减仓"}]}'
        return {
            "success": True,
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "payload": {"result": {"payloads": [{"text": text}]}},
        }


class _AccountEngine:
    def __init__(self) -> None:
        self.positions: dict[str, dict | None] = {}

    def account(self, coin: str):
        return type("Account", (), {"position": self.positions.get(coin.upper())})()


def _runtime() -> RuntimeConfig:
    return RuntimeConfig(
        app=AppConfig(),
        risk=RiskConfig(),
        news=NewsConfig(),
        perps=PerpConfig(),
        dispatch=DispatchConfig(scan_interval_seconds=60, llm_fallback_minutes=60),
        strategy=StrategyConfig(),
        workflow=WorkflowConfig(),
    )


class TriggerDispatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = StateStore(Path(self.tmpdir.name) / "state.db")
        self.runtime = _runtime()
        self.runner = _FakeRunner(self.runtime)
        self.dispatcher = TriggerDispatcher(self.runtime, self.store, self.runner)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_dispatch_module_exports_expected_public_api(self) -> None:
        expected_names = [
            "DAILY_STRATEGY_SLOT_LOCK_PREFIX",
            "DispatchAction",
            "OpenClawAgentRunner",
            "TriggerDispatcher",
            "build_dispatcher",
            "run_strategy_refresh",
        ]
        for name in expected_names:
            self.assertTrue(hasattr(dispatch_module, name), name)

    def test_plan_event_action_when_decision_requests_notification(self) -> None:
        decision = AutopilotDecision(
            phase=AutopilotPhase.confirm,
            notify_user=True,
            reason="preview_ready",
            product_id="BTC-USDC",
            flow_mode=EntryWorkflowMode.confirm,
            signal=SignalDecision(
                product_id="BTC-USDC",
                side=SignalSide.long,
                confidence=0.8,
                reason="test",
                risk_profile=RiskProfile.normal,
            ),
        )
        actions = self.dispatcher.plan_actions(decision, datetime(2026, 3, 3, 1, 0, tzinfo=UTC))
        self.assertEqual([action.kind for action in actions], ["strategy", "event"])

    def test_plan_trade_review_before_event_for_trade_candidate(self) -> None:
        decision = AutopilotDecision(
            phase=AutopilotPhase.trade,
            notify_user=True,
            reason="paper_trade_candidate_ready",
            product_id="BTC-PERP",
            flow_mode=EntryWorkflowMode.auto,
            signal=SignalDecision(
                product_id="BTC-PERP",
                side=SignalSide.short,
                confidence=0.8,
                reason="test",
                risk_profile=RiskProfile.normal,
            ),
            preview={"plan": {"action": "open", "side": "short", "notional_usd": "10", "coin": "BTC"}},
        )
        self.runtime.dispatch.market_mode = "perps"
        actions = self.dispatcher.plan_actions(decision, datetime(2026, 3, 3, 1, 0, tzinfo=UTC))
        self.assertEqual([action.kind for action in actions], ["strategy", "trade_review"])

    def test_plan_fallback_when_no_recent_llm_trigger(self) -> None:
        decision = AutopilotDecision(
            phase=AutopilotPhase.heartbeat,
            notify_user=False,
            reason="no_action",
            product_id="BTC-USDC",
            flow_mode=EntryWorkflowMode.confirm,
        )
        actions = self.dispatcher.plan_actions(decision, datetime(2026, 3, 3, 1, 0, tzinfo=UTC))
        self.assertEqual([action.kind for action in actions], ["strategy"])

    def test_plan_strategy_rewrite_on_major_news(self) -> None:
        now = datetime(2026, 3, 3, 2, 0, tzinfo=UTC)
        self.store.set_value("strategy:last_updated_at", datetime(2026, 3, 3, 1, 0, tzinfo=UTC).isoformat())
        self.store.set_value("strategy:last_strategy_date", "2026-03-03")
        self.runtime.dispatch.enable_observe_notifications = True
        decision = AutopilotDecision(
            phase=AutopilotPhase.observe,
            notify_user=True,
            reason="major_news",
            product_id="BTC-USDC",
            flow_mode=EntryWorkflowMode.confirm,
            latest_news=[
                NewsItem(
                    source="fed-press-monetary",
                    title="FOMC statement",
                    url="https://example.com/fomc",
                    layer="macro",
                    severity="high",
                )
            ],
        )
        actions = self.dispatcher.plan_actions(decision, now)
        self.assertEqual([action.kind for action in actions], ["strategy", "event"])

    def test_plan_strategy_rewrite_on_major_news_skips_observe_event_when_disabled(self) -> None:
        now = datetime(2026, 3, 3, 2, 0, tzinfo=UTC)
        self.store.set_value("strategy:last_updated_at", datetime(2026, 3, 3, 1, 0, tzinfo=UTC).isoformat())
        self.store.set_value("strategy:last_strategy_date", "2026-03-03")
        decision = AutopilotDecision(
            phase=AutopilotPhase.observe,
            notify_user=True,
            reason="major_news",
            product_id="BTC-USDC",
            flow_mode=EntryWorkflowMode.confirm,
            latest_news=[
                NewsItem(
                    source="fed-press-monetary",
                    title="FOMC statement",
                    url="https://example.com/fomc",
                    layer="macro",
                    severity="high",
                )
            ],
        )
        actions = self.dispatcher.plan_actions(decision, now)
        self.assertEqual([action.kind for action in actions], ["strategy"])

    def test_plan_triggers_scheduled_recheck(self) -> None:
        now = datetime(2026, 3, 3, 2, 0, tzinfo=UTC)
        self.store.set_value("strategy:last_updated_at", datetime(2026, 3, 3, 1, 45, tzinfo=UTC).isoformat())
        self.store.set_value("strategy:last_strategy_date", "2026-03-03")
        self.store.set_value("strategy:last_strategy_slot", "2026-03-03@09")
        self.store.set_value("dispatch:last_llm_trigger_at", now.isoformat())
        decision = AutopilotDecision(
            phase=AutopilotPhase.heartbeat,
            notify_user=False,
            reason="no_action",
            product_id="BTC-PERP",
            flow_mode=EntryWorkflowMode.auto,
        )
        with patch(
            "openclaw_trader.dispatch.load_current_strategy",
            return_value={
                "market_regime": "neutral_consolidation",
                "risk_mode": "normal",
                "scheduled_rechecks": [
                    {
                        "fingerprint": "fomc-2026-03-19",
                        "event_at": "2026-03-19T02:00:00+00:00",
                        "run_at": "2026-03-03T01:30:00+00:00",
                        "reason": "T-30m FOMC pre-check",
                    }
                ],
            },
        ):
            actions = self.dispatcher.plan_actions(decision, now)
        self.assertEqual([action.kind for action in actions], ["strategy"])
        self.assertEqual(actions[0].reason, "scheduled_recheck:fomc-2026-03-19")
        self.assertEqual(
            actions[0].state_mark_key,
            "strategy:scheduled_recheck:fomc-2026-03-19|2026-03-03T01:30:00+00:00",
        )

    def test_plan_uses_routine_refresh_as_last_resort_once_per_day(self) -> None:
        now = datetime(2026, 3, 3, 2, 0, tzinfo=UTC)
        self.store.set_value("strategy:last_strategy_slot", "2026-03-02@21")
        decision = AutopilotDecision(
            phase=AutopilotPhase.heartbeat,
            notify_user=False,
            reason="no_action",
            product_id="BTC-PERP",
            flow_mode=EntryWorkflowMode.auto,
        )
        with patch(
            "openclaw_trader.dispatch.load_current_strategy",
            return_value={
                "market_regime": "neutral_consolidation",
                "risk_mode": "normal",
                "scheduled_rechecks": [],
            },
        ):
            actions = self.dispatcher.plan_actions(decision, now)
        self.assertEqual([action.kind for action in actions], ["strategy"])
        self.assertEqual(actions[0].reason, "routine_refresh")
        self.assertEqual(actions[0].state_mark_key, "2026-03-03@09")

        self.store.set_value("strategy:last_strategy_date", "2026-03-03")
        self.store.set_value("dispatch:last_llm_trigger_at", now.isoformat())
        with patch(
            "openclaw_trader.dispatch.load_current_strategy",
            return_value={
                "market_regime": "neutral_consolidation",
                "risk_mode": "normal",
                "scheduled_rechecks": [],
            },
        ):
            actions = self.dispatcher.plan_actions(decision, now)
        self.assertEqual([action.kind for action in actions], [])

    def test_dispatch_once_marks_daily_report(self) -> None:
        now = datetime(2026, 3, 3, 13, 0, tzinfo=UTC)  # 21:00 Asia/Shanghai
        decision = AutopilotDecision(
            phase=AutopilotPhase.heartbeat,
            notify_user=False,
            reason="no_action",
            product_id="BTC-USDC",
            flow_mode=EntryWorkflowMode.confirm,
        )
        self.runtime.dispatch.market_mode = "spot"
        with patch("openclaw_trader.dispatch.load_runtime_config", return_value=self.runtime), \
             patch("openclaw_trader.dispatch.load_coinbase_credentials", return_value=object()), \
             patch("openclaw_trader.dispatch.CoinbaseAdvancedClient", return_value=object()), \
             patch("openclaw_trader.dispatch.TraderEngine.autopilot_check", return_value=decision), \
             patch("openclaw_trader.dispatch.write_dispatch_brief", return_value={}), \
             patch("openclaw_trader.dispatch.build_strategy_input", return_value={}):
            result = self.dispatcher.dispatch_once(now=now)
        self.assertEqual([item["kind"] for item in result["actions"]], ["strategy", "daily_report"])
        self.assertEqual([call[0] for call in self.runner.calls], ["strategy", "daily_report"])
        self.assertEqual(len(self.runner.sent_texts), 1)
        self.assertIn("📘 日报", self.runner.sent_texts[0])
        self.assertEqual(self.store.get_value("dispatch:last_daily_report_date"), "2026-03-03")
        self.assertEqual(self.store.get_value("dispatch:last_llm_trigger_at"), now.isoformat())

    def test_dispatch_once_event_delivery_uses_safe_text_fallback(self) -> None:
        now = datetime(2026, 3, 3, 2, 0, tzinfo=UTC)
        self.runtime.dispatch.enable_observe_notifications = True
        decision = AutopilotDecision(
            phase=AutopilotPhase.observe,
            notify_user=True,
            reason="major_news",
            product_id="BTC-USDC",
            flow_mode=EntryWorkflowMode.confirm,
            signal=SignalDecision(
                product_id="BTC-USDC",
                side=SignalSide.long,
                confidence=0.77,
                reason="watch",
                risk_profile=RiskProfile.normal,
            ),
        )
        self.runtime.dispatch.market_mode = "spot"
        with patch("openclaw_trader.dispatch.load_runtime_config", return_value=self.runtime), \
             patch("openclaw_trader.dispatch.load_coinbase_credentials", return_value=object()), \
             patch("openclaw_trader.dispatch.CoinbaseAdvancedClient", return_value=object()), \
             patch("openclaw_trader.dispatch.TraderEngine.autopilot_check", return_value=decision), \
             patch("openclaw_trader.dispatch.write_dispatch_brief", return_value={}), \
             patch("openclaw_trader.dispatch.build_strategy_input", return_value={}):
            result = self.dispatcher.dispatch_once(now=now)
        self.assertEqual([item["kind"] for item in result["actions"]], ["strategy", "event"])
        self.assertEqual([call[0] for call in self.runner.calls], ["strategy", "event"])
        self.assertEqual(len(self.runner.sent_texts), 1)
        self.assertIn("BTC-USDC", self.runner.sent_texts[0])
        self.assertIn("原因：major_news", self.runner.sent_texts[0])

    def test_dispatch_once_skips_daily_strategy_when_slot_lock_exists(self) -> None:
        now = datetime(2026, 3, 5, 1, 0, tzinfo=UTC)  # 09:00 Asia/Shanghai
        decision = AutopilotDecision(
            phase=AutopilotPhase.heartbeat,
            notify_user=False,
            reason="no_action",
            product_id="BTC-USDC",
            flow_mode=EntryWorkflowMode.confirm,
        )
        self.runtime.dispatch.market_mode = "spot"
        self.store.set_value("strategy:last_strategy_slot", "2026-03-04@21")
        self.store.set_value(
            f"{DAILY_STRATEGY_SLOT_LOCK_PREFIX}2026-03-05@09",
            now.isoformat(),
            now=now,
        )
        with patch("openclaw_trader.dispatch.load_runtime_config", return_value=self.runtime), \
             patch("openclaw_trader.dispatch.load_current_strategy", return_value={"version": 1}), \
             patch("openclaw_trader.dispatch.load_coinbase_credentials", return_value=object()), \
             patch("openclaw_trader.dispatch.CoinbaseAdvancedClient", return_value=object()), \
             patch("openclaw_trader.dispatch.TraderEngine.autopilot_check", return_value=decision), \
             patch("openclaw_trader.dispatch.write_dispatch_brief", return_value={}), \
             patch("openclaw_trader.dispatch.build_strategy_input", return_value={}):
            result = self.dispatcher.dispatch_once(now=now)
        self.assertEqual([call[0] for call in self.runner.calls], [])
        self.assertEqual([item["kind"] for item in result["actions"]], ["strategy"])
        self.assertEqual(result["actions"][0]["reason"], "routine_refresh")
        strategy_results = [item for item in result["results"] if item["kind"] == "strategy"]
        self.assertEqual(len(strategy_results), 1)
        self.assertTrue(strategy_results[0]["skipped"])
        self.assertEqual(strategy_results[0]["skip_reason"], "daily_strategy_slot_locked")

    def test_run_forever_sleeps_between_dispatches(self) -> None:
        self.runtime.dispatch.scan_interval_seconds = 45
        with patch.object(self.dispatcher, "dispatch_once", side_effect=[RuntimeError("boom"), KeyboardInterrupt()]) as dispatch_once, \
             patch("openclaw_trader.dispatch.time.sleep", return_value=None) as sleep, \
             patch("openclaw_trader.dispatch.traceback.print_exc", return_value=None), \
             patch("openclaw_trader.dispatch.sys.stderr", new_callable=io.StringIO):
            with self.assertRaises(KeyboardInterrupt):
                self.dispatcher.run_forever()
        self.assertEqual(dispatch_once.call_count, 2)
        self.assertEqual(sleep.call_count, 1)
        sleep.assert_called_with(45)


class OpenClawAgentRunnerTests(unittest.TestCase):
    def test_session_target_rotates_by_day(self) -> None:
        runner = OpenClawAgentRunner(_runtime())
        action = type("Action", (), {"kind": "event", "reason": "preview_ready", "message": "noop"})()
        first = runner._session_target_for_action(action, datetime(2026, 3, 3, 1, 0, tzinfo=UTC))
        second = runner._session_target_for_action(action, datetime(2026, 3, 4, 1, 0, tzinfo=UTC))
        self.assertNotEqual(first, second)

    def test_run_returns_timeout_result(self) -> None:
        runner = OpenClawAgentRunner(_runtime())
        action = type("Action", (), {"kind": "event", "reason": "preview_ready", "message": "noop", "deliver": False})()
        with patch("openclaw_trader.dispatch.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["openclaw"], timeout=195)):
            result = runner.run(action, now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC))
        self.assertFalse(result["success"])
        self.assertTrue(result["timeout"])


class DispatchPerpsTradeReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = StateStore(Path(self.tmpdir.name) / "state.db")
        self.report_dir = Path(self.tmpdir.name) / "reports"
        self.report_dir.mkdir(parents=True, exist_ok=True)
        runtime = _runtime()
        runtime.dispatch.market_mode = "perps"
        runtime.workflow.entry_mode = EntryWorkflowMode.auto
        self.runtime = runtime
        self.runner = _TradeReviewRunner(self.runtime)
        self.dispatcher = TriggerDispatcher(self.runtime, self.store, self.runner)
        self.strategy_patches = [
            patch("openclaw_trader.strategy.REPORT_DIR", self.report_dir),
            patch("openclaw_trader.strategy.STRATEGY_DAY_JSON", self.report_dir / "strategy-day.json"),
            patch("openclaw_trader.strategy.STRATEGY_DAY_MD", self.report_dir / "strategy-day.md"),
            patch("openclaw_trader.strategy.STRATEGY_HISTORY_JSONL", self.report_dir / "strategy-history.jsonl"),
            patch("openclaw_trader.strategy.POSITION_JOURNAL_JSONL", self.report_dir / "position-journal.jsonl"),
            patch("openclaw_trader.strategy.STRATEGY_CHANGE_LOG_JSONL", self.report_dir / "strategy-change-log.jsonl"),
        ]
        for patcher in self.strategy_patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.strategy_patches):
            patcher.stop()
        self.tmpdir.cleanup()

    def test_apply_trade_review_scales_notional(self) -> None:
        decision = AutopilotDecision(
            phase=AutopilotPhase.trade,
            notify_user=False,
            reason="paper_trade_candidate_ready",
            product_id="BTC-PERP",
            flow_mode=EntryWorkflowMode.auto,
            signal=SignalDecision(
                product_id="BTC-PERP",
                side=SignalSide.short,
                confidence=0.8,
                reason="test",
                risk_profile=RiskProfile.normal,
            ),
            risk=RiskEvaluation(
                approved=True,
                reason="approved",
                max_allowed_quote_usd="8",
            ),
            preview={"plan": {"action": "open", "side": "short", "notional_usd": "10", "margin_usd": "5", "execution_leverage": "2", "coin": "BTC"}},
        )
        plan = self.dispatcher._scale_trade_plan(decision, review_decision="approve", size_scale=0.5)
        self.assertEqual(plan["notional_usd"], "5.00000000")
        self.assertEqual(plan["margin_usd"], "2.50000000")

    def test_apply_trade_review_can_turn_close_into_reduce(self) -> None:
        decision = AutopilotDecision(
            phase=AutopilotPhase.trade,
            notify_user=False,
            reason="paper_trade_candidate_ready",
            product_id="BTC-PERP",
            flow_mode=EntryWorkflowMode.auto,
            signal=SignalDecision(
                product_id="BTC-PERP",
                side=SignalSide.flat,
                confidence=0.6,
                reason="rebalance down",
                risk_profile=RiskProfile.normal,
            ),
            preview={"plan": {"action": "close", "side": "long", "notional_usd": "12", "margin_usd": "6", "execution_leverage": "2", "coin": "BTC", "minimum_trade_notional_usd": "5"}},
        )
        plan = self.dispatcher._scale_trade_plan(decision, review_decision="approve", size_scale=0.5)
        self.assertEqual(plan["action"], "reduce")
        self.assertEqual(plan["notional_usd"], "6.00000000")
        self.assertEqual(plan["margin_usd"], "3.00000000")

    def test_approved_trade_plans_normalize_review_reason_to_effective_plan(self) -> None:
        decision = AutopilotDecision(
            phase=AutopilotPhase.trade,
            notify_user=False,
            reason="paper_trade_candidate_ready",
            product_id="SOL-PERP",
            flow_mode=EntryWorkflowMode.auto,
            signal=SignalDecision(
                product_id="SOL-PERP",
                side=SignalSide.flat,
                confidence=0.6,
                reason="close",
                risk_profile=RiskProfile.normal,
            ),
            preview={
                "plan": {
                    "action": "close",
                    "side": "short",
                    "notional_usd": "12",
                    "margin_usd": "12",
                    "execution_leverage": "1",
                    "coin": "SOL",
                    "minimum_trade_notional_usd": "5",
                }
            },
        )
        fake_system_state = type(
            "FakePerpState",
            (),
            {
                "primary": decision,
                "decisions": [decision],
                "latest_news": [],
            },
        )()
        trade_review = LlmTradeReviewDecision(
            decision="approve",
            reason="batch",
            orders=[
                LlmTradeReviewOrderDecision(
                    product_id="SOL-PERP",
                    decision="approve",
                    size_scale=1.0,
                    reason="减仓 50%，保留半仓",
                )
            ],
        )
        approved = self.dispatcher._approved_trade_plans(fake_system_state, trade_review)
        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0]["review"]["llm_reason"], "减仓 50%，保留半仓")
        self.assertEqual(approved[0]["review"]["reason"], "按结构化审核执行：全平 SOL-PERP 空。")
        self.assertEqual(approved[0]["review"]["effective_action"], "close")
        self.assertEqual(approved[0]["review"]["effective_size_scale"], 1.0)

    def test_should_emit_trade_event_for_auto_execution_even_when_notify_flag_is_false(self) -> None:
        decision = AutopilotDecision(
            phase=AutopilotPhase.trade,
            notify_user=False,
            reason="paper_trade_candidate_ready",
            product_id="BTC-PERP",
            flow_mode=EntryWorkflowMode.auto,
        )
        approved_trade_plans = [
            {
                "decision": decision,
                "plan": {"action": "open", "side": "short", "notional_usd": "10"},
                "review": {"reason": "按结构化审核执行：开仓 BTC-PERP 空。"},
            }
        ]
        executed_trades = [
            {
                "product_id": "BTC-PERP",
                "approved_plan": {"action": "open", "side": "short", "notional_usd": "10"},
                "review": {"reason": "按结构化审核执行：开仓 BTC-PERP 空。"},
                "success": True,
            }
        ]
        self.assertTrue(
            should_emit_trade_event(
                decision,
                LlmTradeReviewDecision(decision="approve", reason="ok"),
                approved_trade_plans,
                executed_trades,
                market_mode="perps",
            )
        )

    def test_dispatch_once_perps_executes_all_approved_candidates_after_trade_review(self) -> None:
        primary = AutopilotDecision(
            phase=AutopilotPhase.trade,
            notify_user=True,
            reason="paper_trade_candidate_ready",
            product_id="BTC-PERP",
            flow_mode=EntryWorkflowMode.auto,
            signal=SignalDecision(
                product_id="BTC-PERP",
                side=SignalSide.short,
                confidence=0.8,
                reason="test",
                risk_profile=RiskProfile.normal,
            ),
            risk=RiskEvaluation(
                approved=True,
                reason="approved",
                max_allowed_quote_usd="8",
            ),
            preview={"plan": {"action": "open", "side": "short", "notional_usd": "10", "margin_usd": "5", "execution_leverage": "2", "coin": "BTC"}},
        )
        secondary = AutopilotDecision(
            phase=AutopilotPhase.trade,
            notify_user=True,
            reason="paper_trade_candidate_ready",
            product_id="ETH-PERP",
            flow_mode=EntryWorkflowMode.auto,
            signal=SignalDecision(
                product_id="ETH-PERP",
                side=SignalSide.short,
                confidence=0.8,
                reason="test",
                risk_profile=RiskProfile.normal,
            ),
            risk=RiskEvaluation(
                approved=True,
                reason="approved",
                max_allowed_quote_usd="8",
            ),
            preview={"plan": {"action": "open", "side": "short", "notional_usd": "12", "margin_usd": "6", "execution_leverage": "2", "coin": "ETH"}},
        )
        fake_system_state = type(
            "FakePerpState",
            (),
            {
                "primary": primary,
                "decisions": [primary, secondary],
                "latest_news": [],
            },
        )()
        portfolio = PerpPaperPortfolio(
            exchange="hyperliquid",
            starting_equity_usd="207.21",
            realized_pnl_usd="0",
            unrealized_pnl_usd="0",
            total_equity_usd="207.21",
            available_equity_usd="207.21",
            total_exposure_usd="0",
            positions=[],
        )
        fake_engine = _AccountEngine()
        with patch("openclaw_trader.dispatch.load_runtime_config", return_value=self.runtime), \
             patch("openclaw_trader.dispatch.sync_news", return_value=None), \
             patch("openclaw_trader.dispatch.build_perp_engine", return_value=fake_engine), \
             patch("openclaw_trader.dispatch.write_perp_news_brief", return_value={}), \
             patch("openclaw_trader.dispatch.build_strategy_input_perps", return_value={"recommended_limits": {"BTC-PERP": {"max_position_share_pct": 20.0, "max_order_share_pct": 8.0}}}), \
             patch("openclaw_trader.dispatch.write_perp_dispatch_brief", return_value={}), \
             patch("openclaw_trader.dispatch.PerpSupervisor.system_state", return_value=fake_system_state), \
             patch("openclaw_trader.dispatch.PerpSupervisor.portfolio", return_value=portfolio), \
             patch("openclaw_trader.dispatch.PerpSupervisor.apply_trade_plan", side_effect=[{"coin": "BTC", "results": [{"success": True}]}, {"coin": "ETH", "results": [{"success": True}]}]) as apply_trade:
            result = self.dispatcher.dispatch_once(now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC))
        self.assertEqual(apply_trade.call_count, 2)
        self.assertEqual(result["trade_review"]["decision"], "approve")
        self.assertEqual(result["executed_trades"][0]["product_id"], "BTC-PERP")
        self.assertEqual(result["executed_trades"][1]["product_id"], "ETH-PERP")
        journal_lines = (self.report_dir / "position-journal.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(journal_lines), 2)
        first_journal = json.loads(journal_lines[0])
        self.assertEqual(first_journal["strategy_version"], 1)
        self.assertEqual(first_journal["product_id"], "BTC-PERP")
        self.assertEqual(first_journal["approved_plan"]["margin_usd"], "2.50000000")
        self.assertEqual(first_journal["review"]["stop_loss_price"], "91000")
        self.assertEqual(first_journal["review"]["take_profit_price"], "84000")
        self.assertEqual(first_journal["review"]["exit_plan"], "若反弹失效则尽快回补")
        self.assertEqual([call[0] for call in self.runner.calls], ["strategy", "strategy_notify", "trade_review"])
        self.assertEqual(len(self.runner.sent_texts), 2)
        self.assertIn("📊 策略更新", self.runner.sent_texts[0])
        self.assertIn("🔵💰", self.runner.sent_texts[1])
        self.assertIn("BTC-PERP", self.runner.sent_texts[1])

    def test_dispatch_once_perps_skips_event_when_trade_review_rejects(self) -> None:
        class _RejectRunner(_FakeRunner):
            def run(self, action, *, now=None):  # type: ignore[override]
                self.calls.append((action.kind, action.deliver))
                text = "{}"
                if action.kind == "strategy":
                    text = '{"strategy_date":"2026-03-03","market_regime":"trend","risk_mode":"normal","summary":"ok","invalidators":[],"symbols":[{"symbol":"BTC-PERP","bias":"short","max_position_share_pct":20,"max_order_share_pct":8,"thesis":"ok"}]}'
                elif action.kind == "trade_review":
                    text = '{"decision":"reject","reason":"news_conflict","orders":[{"product_id":"BTC-PERP","decision":"reject","size_scale":0,"reason":"news_conflict"}]}'
                return {
                    "success": True,
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                    "payload": {"result": {"payloads": [{"text": text}]}},
                }

        runner = _RejectRunner(self.runtime)
        dispatcher = TriggerDispatcher(self.runtime, self.store, runner)
        primary = AutopilotDecision(
            phase=AutopilotPhase.trade,
            notify_user=True,
            reason="paper_trade_candidate_ready",
            product_id="BTC-PERP",
            flow_mode=EntryWorkflowMode.auto,
            signal=SignalDecision(
                product_id="BTC-PERP",
                side=SignalSide.short,
                confidence=0.8,
                reason="test",
                risk_profile=RiskProfile.normal,
            ),
            risk=RiskEvaluation(
                approved=True,
                reason="approved",
                max_allowed_quote_usd="8",
            ),
            preview={"plan": {"action": "open", "side": "short", "notional_usd": "10", "coin": "BTC"}},
        )
        fake_system_state = type(
            "FakePerpState",
            (),
            {
                "primary": primary,
                "decisions": [primary],
                "latest_news": [],
            },
        )()
        portfolio = PerpPaperPortfolio(
            exchange="hyperliquid",
            starting_equity_usd="207.21",
            realized_pnl_usd="0",
            unrealized_pnl_usd="0",
            total_equity_usd="207.21",
            available_equity_usd="207.21",
            total_exposure_usd="0",
            positions=[],
        )
        fake_engine = _AccountEngine()
        with patch("openclaw_trader.dispatch.load_runtime_config", return_value=self.runtime), \
             patch("openclaw_trader.dispatch.sync_news", return_value=None), \
             patch("openclaw_trader.dispatch.build_perp_engine", return_value=fake_engine), \
             patch("openclaw_trader.dispatch.write_perp_news_brief", return_value={}), \
             patch("openclaw_trader.dispatch.build_strategy_input_perps", return_value={"recommended_limits": {"BTC-PERP": {"max_position_share_pct": 20.0, "max_order_share_pct": 8.0}}}), \
             patch("openclaw_trader.dispatch.write_perp_dispatch_brief", return_value={}), \
             patch("openclaw_trader.dispatch.PerpSupervisor.system_state", return_value=fake_system_state), \
             patch("openclaw_trader.dispatch.PerpSupervisor.portfolio", return_value=portfolio), \
             patch("openclaw_trader.dispatch.PerpSupervisor.apply_trade_plan", return_value=None):
            result = dispatcher.dispatch_once(now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC))
        self.assertEqual([call[0] for call in runner.calls], ["strategy", "strategy_notify", "trade_review"])
        self.assertEqual(result["trade_review"]["decision"], "reject")
        self.assertEqual(len(runner.sent_texts), 1)
        self.assertIn("📊 策略更新", runner.sent_texts[0])

    def test_dispatch_once_perps_skips_event_when_approved_plan_is_empty(self) -> None:
        primary = AutopilotDecision(
            phase=AutopilotPhase.trade,
            notify_user=True,
            reason="paper_trade_candidate_ready",
            product_id="BTC-PERP",
            flow_mode=EntryWorkflowMode.auto,
            signal=SignalDecision(
                product_id="BTC-PERP",
                side=SignalSide.short,
                confidence=0.8,
                reason="test",
                risk_profile=RiskProfile.normal,
            ),
            risk=RiskEvaluation(
                approved=True,
                reason="approved",
                max_allowed_quote_usd="0",
            ),
            preview={"plan": {"action": "open", "side": "short", "notional_usd": "10", "coin": "BTC"}},
        )
        fake_system_state = type(
            "FakePerpState",
            (),
            {
                "primary": primary,
                "decisions": [primary],
                "latest_news": [],
            },
        )()
        portfolio = PerpPaperPortfolio(
            exchange="hyperliquid",
            starting_equity_usd="207.21",
            realized_pnl_usd="0",
            unrealized_pnl_usd="0",
            total_equity_usd="207.21",
            available_equity_usd="207.21",
            total_exposure_usd="0",
            positions=[],
        )
        fake_engine = _AccountEngine()
        with patch("openclaw_trader.dispatch.load_runtime_config", return_value=self.runtime), \
             patch("openclaw_trader.dispatch.sync_news", return_value=None), \
             patch("openclaw_trader.dispatch.build_perp_engine", return_value=fake_engine), \
             patch("openclaw_trader.dispatch.write_perp_news_brief", return_value={}), \
             patch("openclaw_trader.dispatch.build_strategy_input_perps", return_value={"recommended_limits": {"BTC-PERP": {"max_position_share_pct": 20.0, "max_order_share_pct": 8.0}}}), \
             patch("openclaw_trader.dispatch.write_perp_dispatch_brief", return_value={}), \
             patch("openclaw_trader.dispatch.PerpSupervisor.system_state", return_value=fake_system_state), \
             patch("openclaw_trader.dispatch.PerpSupervisor.portfolio", return_value=portfolio), \
             patch("openclaw_trader.dispatch.PerpSupervisor.apply_trade_plan", return_value=None):
            result = self.dispatcher.dispatch_once(now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC))
        self.assertEqual([call[0] for call in self.runner.calls], ["strategy", "strategy_notify", "trade_review"])
        self.assertEqual(result["trade_review"]["decision"], "approve")
        self.assertEqual(len(self.runner.sent_texts), 1)
        self.assertIn("📊 策略更新", self.runner.sent_texts[0])

    def test_dispatch_once_perps_skips_trade_review_when_strategy_refresh_changes_phase(self) -> None:
        primary = AutopilotDecision(
            phase=AutopilotPhase.trade,
            notify_user=True,
            reason="paper_trade_candidate_ready",
            product_id="BTC-PERP",
            flow_mode=EntryWorkflowMode.auto,
            signal=SignalDecision(
                product_id="BTC-PERP",
                side=SignalSide.short,
                confidence=0.8,
                reason="test",
                risk_profile=RiskProfile.normal,
            ),
            risk=RiskEvaluation(
                approved=True,
                reason="approved",
                max_allowed_quote_usd="8",
            ),
            preview={"plan": {"action": "open", "side": "short", "notional_usd": "10", "coin": "BTC"}},
        )
        refreshed_primary = AutopilotDecision(
            phase=AutopilotPhase.heartbeat,
            notify_user=False,
            reason="no_action",
            product_id="BTC-PERP",
            flow_mode=EntryWorkflowMode.auto,
        )
        initial_state = type(
            "FakePerpState",
            (),
            {
                "primary": primary,
                "decisions": [primary],
                "latest_news": [],
            },
        )()
        refreshed_state = type(
            "FakePerpState",
            (),
            {
                "primary": refreshed_primary,
                "decisions": [refreshed_primary],
                "latest_news": [],
            },
        )()
        initial_state = type(
            "FakePerpState",
            (),
            {
                "primary": primary,
                "decisions": [primary],
                "latest_news": [],
            },
        )()
        portfolio = PerpPaperPortfolio(
            exchange="hyperliquid",
            starting_equity_usd="207.21",
            realized_pnl_usd="0",
            unrealized_pnl_usd="0",
            total_equity_usd="207.21",
            available_equity_usd="207.21",
            total_exposure_usd="0",
            positions=[],
        )
        fake_engine = _AccountEngine()
        with patch("openclaw_trader.dispatch.load_runtime_config", return_value=self.runtime), \
             patch("openclaw_trader.dispatch.sync_news", return_value=None), \
             patch("openclaw_trader.dispatch.build_perp_engine", return_value=fake_engine), \
             patch("openclaw_trader.dispatch.write_perp_news_brief", return_value={}), \
             patch("openclaw_trader.dispatch.build_strategy_input_perps", return_value={"recommended_limits": {"BTC-PERP": {"max_position_share_pct": 20.0, "max_order_share_pct": 8.0}}}), \
             patch("openclaw_trader.dispatch.write_perp_dispatch_brief", return_value={}), \
             patch("openclaw_trader.dispatch.PerpSupervisor.system_state", side_effect=[initial_state, refreshed_state]), \
             patch("openclaw_trader.dispatch.PerpSupervisor.portfolio", return_value=portfolio), \
             patch("openclaw_trader.dispatch.PerpSupervisor.apply_trade_plan", return_value={"coin": "BTC", "results": [{"success": True}]}) as apply_trade:
            result = self.dispatcher.dispatch_once(now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC))
        self.assertEqual([call[0] for call in self.runner.calls], ["strategy", "strategy_notify"])
        review_results = [item for item in result["results"] if item["kind"] == "trade_review"]
        self.assertEqual(len(review_results), 1)
        self.assertTrue(review_results[0]["skipped"])
        self.assertEqual(review_results[0]["skip_reason"], "strategy_refreshed_no_trade_candidate")
        self.assertIsNone(result["trade_review"])
        self.assertEqual(result["decision"]["phase"], "heartbeat")
        self.assertEqual(len(self.runner.sent_texts), 1)
        self.assertIn("📊 策略更新", self.runner.sent_texts[0])
        apply_trade.assert_not_called()

    def test_dispatch_once_perps_triggers_trade_review_when_strategy_refresh_creates_trade_candidate(self) -> None:
        primary = AutopilotDecision(
            phase=AutopilotPhase.heartbeat,
            notify_user=False,
            reason="no_action",
            product_id="BTC-PERP",
            flow_mode=EntryWorkflowMode.auto,
        )
        refreshed_primary = AutopilotDecision(
            phase=AutopilotPhase.trade,
            notify_user=False,
            reason="paper_trade_candidate_ready",
            product_id="BTC-PERP",
            flow_mode=EntryWorkflowMode.auto,
            signal=SignalDecision(
                product_id="BTC-PERP",
                side=SignalSide.short,
                confidence=0.8,
                reason="test",
                risk_profile=RiskProfile.normal,
            ),
            risk=RiskEvaluation(
                approved=True,
                reason="approved",
                max_allowed_quote_usd="8",
            ),
            preview={"plan": {"action": "open", "side": "short", "notional_usd": "10", "coin": "BTC"}},
        )
        initial_state = type(
            "FakePerpState",
            (),
            {
                "primary": primary,
                "decisions": [primary],
                "latest_news": [],
            },
        )()
        refreshed_state = type(
            "FakePerpState",
            (),
            {
                "primary": refreshed_primary,
                "decisions": [refreshed_primary],
                "latest_news": [],
            },
        )()
        initial_state = type(
            "FakePerpState",
            (),
            {
                "primary": primary,
                "decisions": [primary],
                "latest_news": [],
            },
        )()
        portfolio = PerpPaperPortfolio(
            exchange="hyperliquid",
            starting_equity_usd="207.21",
            realized_pnl_usd="0",
            unrealized_pnl_usd="0",
            total_equity_usd="207.21",
            available_equity_usd="207.21",
            total_exposure_usd="0",
            positions=[],
        )
        fake_engine = _AccountEngine()
        brief_calls: list[dict | None] = []

        def _capture_perp_brief(_supervisor, _system_state, *, transition_context=None, trade_review=None, execution_result=None):
            brief_calls.append(transition_context)
            return {}

        with patch("openclaw_trader.dispatch.load_runtime_config", return_value=self.runtime), \
             patch("openclaw_trader.dispatch.sync_news", return_value=None), \
             patch("openclaw_trader.dispatch.build_perp_engine", return_value=fake_engine), \
             patch("openclaw_trader.dispatch.write_perp_news_brief", return_value={}), \
             patch("openclaw_trader.dispatch.build_strategy_input_perps", return_value={"recommended_limits": {"BTC-PERP": {"max_position_share_pct": 20.0, "max_order_share_pct": 8.0}}}), \
             patch("openclaw_trader.dispatch.write_perp_dispatch_brief", side_effect=_capture_perp_brief), \
             patch("openclaw_trader.dispatch.PerpSupervisor.system_state", side_effect=[initial_state, refreshed_state]), \
             patch("openclaw_trader.dispatch.PerpSupervisor.portfolio", return_value=portfolio), \
             patch("openclaw_trader.dispatch.PerpSupervisor.apply_trade_plan", return_value={"coin": "BTC", "results": [{"success": True}]}) as apply_trade:
            result = self.dispatcher.dispatch_once(now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC))
        self.assertEqual([item["kind"] for item in result["actions"]], ["strategy", "trade_review"])
        self.assertEqual([call[0] for call in self.runner.calls], ["strategy", "strategy_notify", "trade_review"])
        self.assertTrue(result["results"][0]["triggered_follow_up_trade_review"])
        self.assertEqual(result["results"][0]["follow_up_trade_review_reason"], "strategy_updated:paper_trade_candidate_ready")
        self.assertEqual(result["trade_review"]["decision"], "approve")
        self.assertEqual(result["decision"]["phase"], "trade")
        apply_trade.assert_called_once()
        self.assertEqual(apply_trade.call_args.args[0], refreshed_primary)
        self.assertEqual(apply_trade.call_args.kwargs["plan_override"]["notional_usd"], "5.00000000")
        self.assertEqual(
            brief_calls[-1],
            {
                "previous_phase": "heartbeat",
                "previous_reason": "no_action",
                "previous_product_id": "BTC-PERP",
                "current_phase": "trade",
                "current_reason": "paper_trade_candidate_ready",
                "current_product_id": "BTC-PERP",
                "transition": "heartbeat->trade",
                "why_now_unblocked": "上一轮因 no_action 暂不执行；当前转为 paper_trade_candidate_ready，已满足本轮处理条件。",
            },
        )

    def test_dispatch_once_perps_suppresses_stale_event_when_strategy_refresh_creates_trade_candidate(self) -> None:
        primary = AutopilotDecision(
            phase=AutopilotPhase.observe,
            notify_user=True,
            reason="major_news",
            product_id="BTC-PERP",
            flow_mode=EntryWorkflowMode.auto,
        )
        refreshed_primary = AutopilotDecision(
            phase=AutopilotPhase.trade,
            notify_user=False,
            reason="paper_trade_candidate_ready",
            product_id="BTC-PERP",
            flow_mode=EntryWorkflowMode.auto,
            signal=SignalDecision(
                product_id="BTC-PERP",
                side=SignalSide.short,
                confidence=0.8,
                reason="test",
                risk_profile=RiskProfile.normal,
            ),
            risk=RiskEvaluation(
                approved=True,
                reason="approved",
                max_allowed_quote_usd="8",
            ),
            preview={"plan": {"action": "open", "side": "short", "notional_usd": "10", "coin": "BTC"}},
        )
        initial_state = type(
            "FakePerpState",
            (),
            {
                "primary": primary,
                "decisions": [primary],
                "latest_news": [],
            },
        )()
        refreshed_state = type(
            "FakePerpState",
            (),
            {
                "primary": refreshed_primary,
                "decisions": [refreshed_primary],
                "latest_news": [],
            },
        )()
        initial_state = type(
            "FakePerpState",
            (),
            {
                "primary": primary,
                "decisions": [primary],
                "latest_news": [],
            },
        )()
        portfolio = PerpPaperPortfolio(
            exchange="hyperliquid",
            starting_equity_usd="207.21",
            realized_pnl_usd="0",
            unrealized_pnl_usd="0",
            total_equity_usd="207.21",
            available_equity_usd="207.21",
            total_exposure_usd="0",
            positions=[],
        )
        fake_engine = _AccountEngine()
        self.runtime.dispatch.enable_observe_notifications = True
        with patch("openclaw_trader.dispatch.load_runtime_config", return_value=self.runtime), \
             patch("openclaw_trader.dispatch.sync_news", return_value=None), \
             patch("openclaw_trader.dispatch.build_perp_engine", return_value=fake_engine), \
             patch("openclaw_trader.dispatch.write_perp_news_brief", return_value={}), \
             patch("openclaw_trader.dispatch.build_strategy_input_perps", return_value={"recommended_limits": {"BTC-PERP": {"max_position_share_pct": 20.0, "max_order_share_pct": 8.0}}}), \
             patch("openclaw_trader.dispatch.write_perp_dispatch_brief", return_value={}), \
             patch("openclaw_trader.dispatch.PerpSupervisor.system_state", side_effect=[initial_state, refreshed_state]), \
             patch("openclaw_trader.dispatch.PerpSupervisor.portfolio", return_value=portfolio), \
             patch("openclaw_trader.dispatch.PerpSupervisor.apply_trade_plan", return_value={"coin": "BTC", "results": [{"success": True}]}) as apply_trade:
            result = self.dispatcher.dispatch_once(now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC))
        self.assertEqual([item["kind"] for item in result["actions"]], ["strategy", "trade_review"])
        self.assertEqual([call[0] for call in self.runner.calls], ["strategy", "strategy_notify", "trade_review"])
        self.assertEqual(result["results"][0]["suppressed_stale_event_count"], 1)
        self.assertEqual(result["trade_review"]["decision"], "approve")
        apply_trade.assert_called_once()
        self.assertEqual(apply_trade.call_args.args[0], refreshed_primary)

    def test_execute_trade_batch_continues_after_single_order_failure(self) -> None:
        primary = AutopilotDecision(
            phase=AutopilotPhase.trade,
            notify_user=True,
            reason="paper_trade_candidate_ready",
            product_id="BTC-PERP",
            flow_mode=EntryWorkflowMode.auto,
            signal=SignalDecision(product_id="BTC-PERP", side=SignalSide.short, confidence=0.8, reason="test", risk_profile=RiskProfile.normal),
            risk=RiskEvaluation(approved=True, reason="approved", max_allowed_quote_usd="8"),
            preview={"plan": {"action": "open", "side": "short", "notional_usd": "10", "coin": "BTC"}},
        )
        secondary = AutopilotDecision(
            phase=AutopilotPhase.trade,
            notify_user=True,
            reason="paper_trade_candidate_ready",
            product_id="ETH-PERP",
            flow_mode=EntryWorkflowMode.auto,
            signal=SignalDecision(product_id="ETH-PERP", side=SignalSide.short, confidence=0.8, reason="test", risk_profile=RiskProfile.normal),
            risk=RiskEvaluation(approved=True, reason="approved", max_allowed_quote_usd="8"),
            preview={"plan": {"action": "open", "side": "short", "notional_usd": "12", "coin": "ETH"}},
        )
        fake_system_state = type("FakePerpState", (), {"primary": primary, "decisions": [primary, secondary], "latest_news": []})()
        portfolio = PerpPaperPortfolio(
            exchange="hyperliquid",
            starting_equity_usd="207.21",
            realized_pnl_usd="0",
            unrealized_pnl_usd="0",
            total_equity_usd="207.21",
            available_equity_usd="207.21",
            total_exposure_usd="0",
            positions=[],
        )
        fake_engine = _AccountEngine()
        with patch("openclaw_trader.dispatch.load_runtime_config", return_value=self.runtime), \
             patch("openclaw_trader.dispatch.sync_news", return_value=None), \
             patch("openclaw_trader.dispatch.build_perp_engine", return_value=fake_engine), \
             patch("openclaw_trader.dispatch.write_perp_news_brief", return_value={}), \
             patch("openclaw_trader.dispatch.build_strategy_input_perps", return_value={"recommended_limits": {}}), \
             patch("openclaw_trader.dispatch.write_perp_dispatch_brief", return_value={}), \
             patch("openclaw_trader.dispatch.PerpSupervisor.system_state", return_value=fake_system_state), \
             patch("openclaw_trader.dispatch.PerpSupervisor.portfolio", return_value=portfolio), \
             patch("openclaw_trader.dispatch.PerpSupervisor.apply_trade_plan", side_effect=[RuntimeError("boom"), {"coin": "ETH", "results": [{"success": True}]}]):
            result = self.dispatcher.dispatch_once(now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC))
        self.assertEqual(len(result["executed_trades"]), 2)
        self.assertFalse(result["executed_trades"][0]["success"])
        self.assertTrue(result["executed_trades"][1]["success"])

    def test_dispatch_once_perps_registers_coin_cooldown_after_successful_panic_exit(self) -> None:
        primary = AutopilotDecision(
            phase=AutopilotPhase.panic_exit,
            notify_user=True,
            reason="risk_layer_approved_emergency_exit",
            product_id="ETH-PERP",
            flow_mode=EntryWorkflowMode.auto,
            panic=EmergencyExitDecision(
                should_exit=True,
                reason="approved_emergency_exit",
                triggers=["position_drawdown_exit"],
            ),
            preview={"plan": {"action": "close", "coin": "ETH"}},
        )
        fake_system_state = type(
            "FakePerpState",
            (),
            {
                "primary": primary,
                "decisions": [primary],
                "latest_news": [],
            },
        )()
        now = datetime(2026, 3, 3, 1, 0, tzinfo=UTC)
        fake_engine = _AccountEngine()
        fake_engine.positions["ETH"] = {"side": "long", "notional_usd": "12"}
        with patch("openclaw_trader.dispatch.load_runtime_config", return_value=self.runtime), \
             patch("openclaw_trader.dispatch.sync_news", return_value=None), \
             patch("openclaw_trader.dispatch.build_perp_engine", return_value=fake_engine), \
             patch.object(self.dispatcher, "plan_actions", return_value=[]), \
             patch("openclaw_trader.dispatch.write_perp_dispatch_brief", return_value={}), \
             patch("openclaw_trader.dispatch.PerpSupervisor.system_state", return_value=fake_system_state), \
             patch("openclaw_trader.dispatch.PerpSupervisor.apply_trade_plan", return_value={"coin": "ETH", "results": [{"success": True}]}) as apply_trade, \
             patch("openclaw_trader.dispatch.PerpSupervisor.register_panic_exit") as register_panic_exit:
            result = self.dispatcher.dispatch_once(now=now)
        apply_trade.assert_called_once_with(primary)
        register_panic_exit.assert_called_once_with(
            now=now,
            coin="ETH",
            trigger_reason="risk_layer_approved_emergency_exit",
            trigger_product_id="ETH-PERP",
            trigger_triggers=["position_drawdown_exit"],
        )
        self.assertEqual(result["decision"]["phase"], "panic_exit")
        self.assertEqual(result["executed_trades"][0]["phase"], "panic_exit")

    def test_dispatch_once_perps_does_not_require_coinbase_credentials(self) -> None:
        primary = AutopilotDecision(
            phase=AutopilotPhase.heartbeat,
            notify_user=False,
            reason="no_action",
            product_id="BTC-PERP",
            flow_mode=EntryWorkflowMode.auto,
        )
        fake_system_state = type(
            "FakePerpState",
            (),
            {
                "primary": primary,
                "decisions": [primary],
                "latest_news": [],
            },
        )()
        with patch("openclaw_trader.dispatch.load_runtime_config", return_value=self.runtime), \
             patch("openclaw_trader.dispatch.load_coinbase_credentials", side_effect=AssertionError("coinbase creds should not be loaded for perps")), \
             patch("openclaw_trader.dispatch.sync_news", return_value=None), \
             patch("openclaw_trader.dispatch.build_perp_engine", return_value=object()), \
             patch("openclaw_trader.dispatch.write_perp_news_brief", return_value={}), \
             patch("openclaw_trader.dispatch.write_perp_dispatch_brief", return_value={}), \
             patch("openclaw_trader.dispatch.build_strategy_input_perps", return_value={"recommended_limits": {}}), \
             patch("openclaw_trader.dispatch.PerpSupervisor.system_state", return_value=fake_system_state):
            result = self.dispatcher.dispatch_once(now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC))
        self.assertEqual(result["decision"]["product_id"], "BTC-PERP")

    def test_run_strategy_refresh_perps_does_not_require_coinbase_credentials(self) -> None:
        strategy_payload = {"recommended_limits": {"BTC-PERP": {"max_position_share_pct": 20.0, "max_order_share_pct": 8.0}}}
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            temp_state = StateStore(tmp / "state.db")
            strategy_input_builder = patch("openclaw_trader.dispatch.build_strategy_input_perps", return_value=strategy_payload)
            with strategy_input_builder as build_strategy_input_perps_mock, \
                 patch("openclaw_trader.dispatch.StateStore", return_value=temp_state), \
                 patch("openclaw_trader.dispatch.load_runtime_config", return_value=self.runtime), \
                 patch("openclaw_trader.dispatch.load_coinbase_credentials", side_effect=AssertionError("coinbase creds should not be loaded for perps")), \
                 patch("openclaw_trader.dispatch.sync_news", return_value=None), \
                 patch("openclaw_trader.dispatch.build_perp_engine", return_value=object()), \
                 patch("openclaw_trader.dispatch.write_perp_news_brief", return_value={}), \
                 patch("openclaw_trader.strategy.REPORT_DIR", tmp), \
                 patch("openclaw_trader.strategy.STRATEGY_DAY_JSON", tmp / "strategy-day.json"), \
                 patch("openclaw_trader.strategy.STRATEGY_DAY_MD", tmp / "strategy-day.md"), \
                 patch("openclaw_trader.strategy.STRATEGY_HISTORY_JSONL", tmp / "strategy-history.jsonl"), \
                 patch("openclaw_trader.strategy.STRATEGY_CHANGE_LOG_JSONL", tmp / "strategy-change-log.jsonl"), \
                 patch.object(OpenClawAgentRunner, "run", return_value={"success": True, "payload": {"result": {"payloads": [{"text": '{"strategy_date":"2026-03-03","market_regime":"trend","risk_mode":"normal","summary":"ok","invalidators":[],"symbols":[{"symbol":"BTC-PERP","bias":"short","max_position_share_pct":20,"max_order_share_pct":8,"thesis":"ok"}]}'}]}}}):
                result = run_strategy_refresh(now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC), reason="test_refresh")
        self.assertTrue(result["success"])
        self.assertEqual(build_strategy_input_perps_mock.call_count, 2)

    def test_run_strategy_refresh_blocks_silent_manual_live_override(self) -> None:
        with patch("openclaw_trader.dispatch.load_runtime_config", return_value=self.runtime):
            result = run_strategy_refresh(
                now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC),
                reason="manual_refresh_no_notify",
                deliver=False,
            )
        self.assertFalse(result["success"])
        self.assertTrue(result["blocked"])
        self.assertEqual(result["reason"], "manual_live_strategy_refresh_requires_delivery")

    def test_run_strategy_refresh_non_manual_silent_refresh_skips_notification(self) -> None:
        strategy_payload = {"recommended_limits": {"BTC-PERP": {"max_position_share_pct": 20.0, "max_order_share_pct": 8.0}}}
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            temp_state = StateStore(tmp / "state.db")
            with patch("openclaw_trader.dispatch.build_strategy_input_perps", return_value=strategy_payload), \
                 patch("openclaw_trader.dispatch.StateStore", return_value=temp_state), \
                 patch("openclaw_trader.dispatch.load_runtime_config", return_value=self.runtime), \
                 patch("openclaw_trader.dispatch.load_coinbase_credentials", side_effect=AssertionError("coinbase creds should not be loaded for perps")), \
                 patch("openclaw_trader.dispatch.sync_news", return_value=None), \
                 patch("openclaw_trader.dispatch.build_perp_engine", return_value=object()), \
                 patch("openclaw_trader.dispatch.write_perp_news_brief", return_value={}), \
                 patch("openclaw_trader.strategy.REPORT_DIR", tmp), \
                 patch("openclaw_trader.strategy.STRATEGY_DAY_JSON", tmp / "strategy-day.json"), \
                 patch("openclaw_trader.strategy.STRATEGY_DAY_MD", tmp / "strategy-day.md"), \
                 patch("openclaw_trader.strategy.STRATEGY_HISTORY_JSONL", tmp / "strategy-history.jsonl"), \
                 patch("openclaw_trader.strategy.STRATEGY_CHANGE_LOG_JSONL", tmp / "strategy-change-log.jsonl"), \
                 patch("openclaw_trader.dispatch._notify_strategy_update") as notify_mock, \
                 patch.object(OpenClawAgentRunner, "run", return_value={"success": True, "payload": {"result": {"payloads": [{"text": '{"strategy_date":"2026-03-03","market_regime":"trend","risk_mode":"normal","summary":"ok","invalidators":[],"symbols":[{"symbol":"BTC-PERP","bias":"short","max_position_share_pct":20,"max_order_share_pct":8,"thesis":"ok"}]}'}]}}}):
                result = run_strategy_refresh(
                    now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC),
                    reason="maintenance_rebuild",
                    deliver=False,
                )
        self.assertTrue(result["success"])
        self.assertTrue(result["strategy_notify"]["skipped"])
        self.assertEqual(result["strategy_notify"]["reason"], "delivery_disabled")
        notify_mock.assert_not_called()

    def test_run_strategy_refresh_deliver_only_sends_strategy_notify(self) -> None:
        strategy_payload = {"recommended_limits": {"BTC-PERP": {"max_position_share_pct": 20.0, "max_order_share_pct": 8.0}}}
        calls: list[tuple[str, bool]] = []
        sent_texts: list[str] = []

        def _runner_call(_runner, action, *, now=None):  # type: ignore[no-untyped-def]
            calls.append((action.kind, action.deliver))
            text = "{}"
            if action.kind == "strategy":
                text = '{"strategy_date":"2026-03-03","market_regime":"trend","risk_mode":"normal","summary":"ok","invalidators":[],"symbols":[{"symbol":"BTC-PERP","bias":"short","max_position_share_pct":20,"max_order_share_pct":8,"thesis":"ok"}]}'
            return {
                "success": True,
                "returncode": 0,
                "stdout": "",
                "stderr": "",
                "payload": {"result": {"payloads": [{"text": text}]}},
            }

        def _send_text(_runner, message: str):  # type: ignore[no-untyped-def]
            sent_texts.append(message)
            return {"success": True, "payload": {}, "text": message}

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            temp_state = StateStore(tmp / "state.db")
            with patch("openclaw_trader.dispatch.build_strategy_input_perps", return_value=strategy_payload), \
                 patch("openclaw_trader.dispatch.StateStore", return_value=temp_state), \
                 patch("openclaw_trader.dispatch.load_runtime_config", return_value=self.runtime), \
                 patch("openclaw_trader.dispatch.load_coinbase_credentials", side_effect=AssertionError("coinbase creds should not be loaded for perps")), \
                 patch("openclaw_trader.dispatch.sync_news", return_value=None), \
                 patch("openclaw_trader.dispatch.build_perp_engine", return_value=object()), \
                 patch("openclaw_trader.dispatch.write_perp_news_brief", return_value={}), \
                 patch("openclaw_trader.strategy.REPORT_DIR", tmp), \
                 patch("openclaw_trader.strategy.STRATEGY_DAY_JSON", tmp / "strategy-day.json"), \
                 patch("openclaw_trader.strategy.STRATEGY_DAY_MD", tmp / "strategy-day.md"), \
                 patch("openclaw_trader.strategy.STRATEGY_HISTORY_JSONL", tmp / "strategy-history.jsonl"), \
                 patch("openclaw_trader.strategy.STRATEGY_CHANGE_LOG_JSONL", tmp / "strategy-change-log.jsonl"), \
                 patch.object(OpenClawAgentRunner, "run", autospec=True, side_effect=_runner_call), \
                 patch.object(OpenClawAgentRunner, "send_text", autospec=True, side_effect=_send_text):
                result = run_strategy_refresh(
                    now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC),
                    reason="manual_refresh",
                    deliver=True,
                )
        self.assertTrue(result["success"])
        self.assertEqual(calls, [("strategy", False), ("strategy_notify", False)])
        self.assertTrue(result["strategy_notify"]["success"])
        self.assertEqual(len(sent_texts), 1)
        self.assertIn("📊 策略更新", sent_texts[0])

    def test_run_strategy_refresh_perps_triggers_follow_up_trade_review(self) -> None:
        strategy_payload = {"recommended_limits": {"BTC-PERP": {"max_position_share_pct": 20.0, "max_order_share_pct": 8.0}}}
        calls: list[tuple[str, bool]] = []
        sent_texts: list[str] = []
        refreshed_primary = AutopilotDecision(
            phase=AutopilotPhase.trade,
            notify_user=False,
            reason="paper_trade_candidate_ready",
            product_id="BTC-PERP",
            flow_mode=EntryWorkflowMode.auto,
            signal=SignalDecision(
                product_id="BTC-PERP",
                side=SignalSide.short,
                confidence=0.8,
                reason="test",
                risk_profile=RiskProfile.normal,
            ),
            risk=RiskEvaluation(
                approved=True,
                reason="approved",
                max_allowed_quote_usd="8",
            ),
            preview={"plan": {"action": "open", "side": "short", "notional_usd": "10", "coin": "BTC"}},
        )
        refreshed_state = type(
            "FakePerpState",
            (),
            {
                "primary": refreshed_primary,
                "decisions": [refreshed_primary],
                "latest_news": [],
            },
        )()
        initial_state = type(
            "FakePerpState",
            (),
            {
                "primary": AutopilotDecision(
                    phase=AutopilotPhase.observe,
                    notify_user=False,
                    reason="fresh_relevant_news_requires_observation",
                    product_id="BTC-PERP",
                    flow_mode=EntryWorkflowMode.auto,
                ),
                "decisions": [
                    AutopilotDecision(
                        phase=AutopilotPhase.observe,
                        notify_user=False,
                        reason="fresh_relevant_news_requires_observation",
                        product_id="BTC-PERP",
                        flow_mode=EntryWorkflowMode.auto,
                    )
                ],
                "latest_news": [],
            },
        )()
        portfolio = PerpPaperPortfolio(
            exchange="hyperliquid",
            starting_equity_usd="207.21",
            realized_pnl_usd="0",
            unrealized_pnl_usd="0",
            total_equity_usd="207.21",
            available_equity_usd="207.21",
            total_exposure_usd="0",
            positions=[],
        )
        fake_engine = _AccountEngine()
        brief_calls: list[dict | None] = []

        def _runner_call(_runner, action, *, now=None):  # type: ignore[no-untyped-def]
            calls.append((action.kind, action.deliver))
            text = "{}"
            if action.kind == "strategy":
                text = '{"strategy_date":"2026-03-03","market_regime":"trend","risk_mode":"normal","summary":"ok","invalidators":[],"symbols":[{"symbol":"BTC-PERP","bias":"short","max_position_share_pct":20,"max_order_share_pct":8,"thesis":"ok"}]}'
            elif action.kind == "trade_review":
                text = '{"decision":"approve","reason":"follow_up_review","orders":[{"product_id":"BTC-PERP","decision":"approve","size_scale":1.0,"reason":"approved"}]}'
            return {
                "success": True,
                "returncode": 0,
                "stdout": "",
                "stderr": "",
                "payload": {"result": {"payloads": [{"text": text}]}},
            }

        def _send_text(_runner, message: str):  # type: ignore[no-untyped-def]
            sent_texts.append(message)
            return {"success": True, "payload": {}, "text": message}

        def _capture_perp_brief(_supervisor, _system_state, *, transition_context=None, trade_review=None, execution_result=None):
            brief_calls.append(transition_context)
            return {}

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            temp_state = StateStore(tmp / "state.db")
            with patch("openclaw_trader.dispatch.build_strategy_input_perps", return_value=strategy_payload), \
                 patch("openclaw_trader.dispatch.StateStore", return_value=temp_state), \
                 patch("openclaw_trader.dispatch.load_runtime_config", return_value=self.runtime), \
                 patch("openclaw_trader.dispatch.load_coinbase_credentials", side_effect=AssertionError("coinbase creds should not be loaded for perps")), \
                 patch("openclaw_trader.dispatch.sync_news", return_value=None), \
                 patch("openclaw_trader.dispatch.build_perp_engine", return_value=fake_engine), \
                 patch("openclaw_trader.dispatch.write_perp_news_brief", return_value={}), \
                 patch("openclaw_trader.dispatch.write_perp_dispatch_brief", side_effect=_capture_perp_brief), \
                 patch("openclaw_trader.dispatch.PerpSupervisor.system_state", side_effect=[initial_state, refreshed_state]), \
                 patch("openclaw_trader.dispatch.PerpSupervisor.portfolio", return_value=portfolio), \
                 patch("openclaw_trader.dispatch.PerpSupervisor.apply_trade_plan", return_value={"coin": "BTC", "results": [{"success": True}]}) as apply_trade, \
                 patch("openclaw_trader.strategy.REPORT_DIR", tmp), \
                 patch("openclaw_trader.strategy.STRATEGY_DAY_JSON", tmp / "strategy-day.json"), \
                 patch("openclaw_trader.strategy.STRATEGY_DAY_MD", tmp / "strategy-day.md"), \
                 patch("openclaw_trader.strategy.STRATEGY_HISTORY_JSONL", tmp / "strategy-history.jsonl"), \
                 patch("openclaw_trader.strategy.POSITION_JOURNAL_JSONL", tmp / "position-journal.jsonl"), \
                 patch("openclaw_trader.strategy.STRATEGY_CHANGE_LOG_JSONL", tmp / "strategy-change-log.jsonl"), \
                 patch.object(OpenClawAgentRunner, "run", autospec=True, side_effect=_runner_call), \
                 patch.object(OpenClawAgentRunner, "send_text", autospec=True, side_effect=_send_text):
                result = run_strategy_refresh(
                    now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC),
                    reason="manual_refresh",
                    deliver=True,
                )
        self.assertTrue(result["success"])
        self.assertEqual(calls, [("strategy", False), ("strategy_notify", False), ("trade_review", False)])
        self.assertEqual(result["decision"]["phase"], "trade")
        self.assertEqual(result["trade_review"]["decision"], "approve")
        self.assertEqual(len(result["executed_trades"]), 1)
        self.assertEqual(len(sent_texts), 2)
        self.assertIn("📊 策略更新", sent_texts[0])
        self.assertIn("🔵💰", sent_texts[1])
        apply_trade.assert_called_once()
        self.assertEqual(
            brief_calls[-1],
            {
                "previous_phase": "observe",
                "previous_reason": "fresh_relevant_news_requires_observation",
                "previous_product_id": "BTC-PERP",
                "current_phase": "trade",
                "current_reason": "paper_trade_candidate_ready",
                "current_product_id": "BTC-PERP",
                "transition": "observe->trade",
                "why_now_unblocked": "上一轮因 fresh_relevant_news_requires_observation 暂不执行；当前转为 paper_trade_candidate_ready，已满足本轮处理条件。",
            },
        )

    def test_format_trade_event_message_lists_all_executed_items(self) -> None:
        decision = AutopilotDecision(
            phase=AutopilotPhase.trade,
            notify_user=True,
            reason="paper_trade_candidate_ready",
            product_id="BTC-PERP",
            flow_mode=EntryWorkflowMode.auto,
        )
        message = format_trade_event_message(
            decision,
            [],
            [
                {
                    "product_id": "BTC-PERP",
                    "approved_plan": {
                        "action": "open",
                        "side": "short",
                        "notional_usd": "12",
                        "margin_usd": "6",
                        "execution_leverage": "2",
                    },
                    "review": {"reason": "btc"},
                },
                {
                    "product_id": "ETH-PERP",
                    "approved_plan": {
                        "action": "add",
                        "side": "short",
                        "notional_usd": "8",
                        "margin_usd": "4",
                        "execution_leverage": "2",
                    },
                    "review": {"reason": "eth"},
                },
            ],
        )
        self.assertIn("本轮共执行 2 笔", message)
        self.assertIn("BTC-PERP", message)
        self.assertIn("ETH-PERP", message)

    def test_format_trade_event_message_prefers_current_position_leverage_for_close(self) -> None:
        decision = AutopilotDecision(
            phase=AutopilotPhase.trade,
            notify_user=True,
            reason="paper_trade_candidate_ready",
            product_id="SOL-PERP",
            flow_mode=EntryWorkflowMode.auto,
        )
        message = format_trade_event_message(
            decision,
            [],
            [
                {
                    "product_id": "SOL-PERP",
                    "approved_plan": {
                        "action": "close",
                        "side": "short",
                        "notional_usd": "30",
                        "execution_leverage": "1",
                        "current_position_leverage": "3",
                    },
                    "review": {"reason": "flat"},
                }
            ],
        )
        self.assertIn("杠杆：3x", message)
        self.assertIn("原始金额：10 USD", message)

    def test_dispatch_once_triggers_scheduled_recheck(self) -> None:
        class _StrategyRunner(_FakeRunner):
            def run(self, action, *, now=None):  # type: ignore[override]
                self.calls.append((action.kind, action.deliver))
                text = "{}"
                if action.kind == "strategy":
                    text = '{"strategy_date":"2026-03-03","market_regime":"trend","risk_mode":"normal","summary":"ok","invalidators":[],"scheduled_rechecks":[],"symbols":[{"symbol":"BTC-PERP","bias":"short","max_position_share_pct":20,"max_order_share_pct":8,"thesis":"ok"}]}'
                return {
                    "success": True,
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                    "payload": {"result": {"payloads": [{"text": text}]}},
                }

        runner = _StrategyRunner(self.runtime)
        dispatcher = TriggerDispatcher(self.runtime, self.store, runner)
        now = datetime(2026, 3, 3, 2, 0, tzinfo=UTC)
        primary = AutopilotDecision(
            phase=AutopilotPhase.heartbeat,
            notify_user=False,
            reason="no_action",
            product_id="BTC-PERP",
            flow_mode=EntryWorkflowMode.auto,
        )
        fake_system_state = type(
            "FakePerpState",
            (),
            {
                "primary": primary,
                "decisions": [primary],
                "latest_news": [],
            },
        )()
        portfolio = PerpPaperPortfolio(
            exchange="hyperliquid",
            starting_equity_usd="207.21",
            realized_pnl_usd="0",
            unrealized_pnl_usd="0",
            total_equity_usd="207.21",
            available_equity_usd="207.21",
            total_exposure_usd="0",
            positions=[],
        )
        current_strategy = {
            "market_regime": "neutral_consolidation",
            "risk_mode": "normal",
            "scheduled_rechecks": [
                {
                    "fingerprint": "fomc-2026-03-19",
                    "event_at": "2026-03-19T02:00:00+00:00",
                    "run_at": "2026-03-03T01:30:00+00:00",
                    "reason": "T-30m FOMC pre-check",
                }
            ],
        }
        self.store.set_value("strategy:last_updated_at", datetime(2026, 3, 3, 1, 45, tzinfo=UTC).isoformat())
        self.store.set_value("strategy:last_strategy_date", "2026-03-03")
        self.store.set_value("strategy:last_strategy_slot", "2026-03-03@09")
        self.store.set_value("dispatch:last_llm_trigger_at", now.isoformat())
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            with patch("openclaw_trader.dispatch.load_runtime_config", return_value=self.runtime), \
                 patch("openclaw_trader.dispatch.load_current_strategy", return_value=current_strategy), \
                 patch("openclaw_trader.dispatch.sync_news", return_value=None), \
                 patch("openclaw_trader.dispatch.build_perp_engine", return_value=object()), \
                 patch("openclaw_trader.dispatch.write_perp_news_brief", return_value={}), \
                 patch("openclaw_trader.dispatch.build_strategy_input_perps", return_value={"recommended_limits": {}}), \
                 patch("openclaw_trader.dispatch.write_perp_dispatch_brief", return_value={}), \
                 patch("openclaw_trader.dispatch.PerpSupervisor.system_state", return_value=fake_system_state), \
                 patch("openclaw_trader.dispatch.PerpSupervisor.portfolio", return_value=portfolio), \
                 patch("openclaw_trader.strategy.STRATEGY_DAY_JSON", tmp / "strategy-day.json"), \
                 patch("openclaw_trader.strategy.STRATEGY_DAY_MD", tmp / "strategy-day.md"), \
                patch("openclaw_trader.strategy.STRATEGY_HISTORY_JSONL", tmp / "strategy-history.jsonl"), \
                 patch("openclaw_trader.strategy.STRATEGY_CHANGE_LOG_JSONL", tmp / "strategy-change-log.jsonl"):
                result = dispatcher.dispatch_once(now=now)
        self.assertEqual([item["kind"] for item in result["actions"]], ["strategy"])
        self.assertEqual(
            self.store.get_value("strategy:scheduled_recheck:fomc-2026-03-19|2026-03-03T01:30:00+00:00"),
            now.isoformat(),
        )


if __name__ == "__main__":
    unittest.main()
