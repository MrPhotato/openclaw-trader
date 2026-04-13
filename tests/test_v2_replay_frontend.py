from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openclaw_trader.modules.replay_frontend import ReplayFrontendService
from openclaw_trader.modules.memory_assets import MemoryAssetsRepository, MemoryAssetsService
from openclaw_trader.shared.infra import SqliteDatabase

from .helpers_v2 import build_test_harness, build_test_settings
from .test_v2_agent_gateway import _valid_strategy_targets


class ReplayFrontendServiceTests(unittest.TestCase):
    def test_query_returns_timeline(self) -> None:
        harness = build_test_harness()
        try:
            service = ReplayFrontendService(harness.container.memory_assets, harness.container.settings)
            view = service.query()
            self.assertEqual(view.render_hints["mode"], "timeline")
        finally:
            harness.cleanup()

    def test_overview_falls_back_to_threshold_overlay_without_policy_guard(self) -> None:
        with TemporaryDirectory() as tmp:
            sqlite_path = Path(tmp) / "state" / "test.db"
            settings = build_test_settings(sqlite_path)
            memory_assets = MemoryAssetsService(MemoryAssetsRepository(SqliteDatabase(sqlite_path)))
            memory_assets.save_asset(
                asset_type="portfolio_snapshot",
                payload={
                    "starting_equity_usd": "1000",
                    "total_equity_usd": "997.5",
                    "available_equity_usd": "800",
                    "total_exposure_usd": "250",
                    "captured_at": "2026-04-09T08:00:00Z",
                },
                trace_id="trace-portfolio",
                actor_role="system",
            )
            service = ReplayFrontendService(memory_assets, settings)
            overview = service.overview()
            self.assertIsNotNone(overview["risk_overlay"])
            self.assertEqual(overview["risk_overlay"]["state"], "fallback")
            self.assertEqual(overview["risk_overlay"]["observe"]["equity_usd"], "988.0")
            self.assertEqual(overview["risk_overlay"]["reduce"]["equity_usd"], "980.0")
            self.assertEqual(overview["risk_overlay"]["exit"]["equity_usd"], "968.0")

    def test_latest_agent_state_exposes_rt_public_brief(self) -> None:
        harness = build_test_harness()
        try:
            gateway = harness.container.agent_gateway
            pm_pack = gateway.pull_pm_runtime_input(trigger_type="pm_main_cron")
            strategy = gateway.submit_strategy(
                input_id=pm_pack.input_id,
                payload={
                    "portfolio_mode": "normal",
                    "target_gross_exposure_band_pct": [0.0, 5.0],
                    "portfolio_thesis": "Replay frontend test strategy",
                    "portfolio_invalidation": "Replay frontend test invalidation",
                    "flip_triggers": "flip when multi-horizon structure and macro regime both reverse",
                    "change_summary": "Replay frontend test summary",
                    "targets": _valid_strategy_targets(
                        btc_band=(1.0, 3.0),
                        btc_rt=1.0,
                    ),
                    "scheduled_rechecks": [],
                },
            )
            rt_pack = gateway.pull_rt_runtime_input(trigger_type="cadence")
            gateway.submit_execution(
                input_id=rt_pack.input_id,
                payload={
                    "decision_id": "decision-replay-1",
                    "strategy_id": strategy["strategy"]["strategy_id"],
                    "generated_at_utc": "2026-03-21T00:00:00Z",
                    "trigger_type": "cadence",
                    "tactical_map_update": {
                        "map_refresh_reason": "pm_strategy_revision",
                        "portfolio_posture": "常规推进",
                        "desk_focus": "先沿着 BTC 逐步推进。",
                        "risk_bias": "风险状态正常，可按策略节奏推进。",
                        "next_review_hint": "等待下一轮 RT cadence。",
                        "coins": [
                            {
                                "coin": "BTC",
                                "working_posture": "先观察再推进",
                                "base_case": "沿主趋势推进。",
                                "first_entry_plan": "若当前仍无仓且 BTC active，就先建立最小试探仓。",
                                "preferred_add_condition": "回踩站稳后继续加仓。",
                                "preferred_reduce_condition": "若结构转弱则减仓。",
                                "reference_take_profit_condition": "冲高分批止盈。",
                                "reference_stop_loss_condition": "跌破关键结构止损。",
                                "no_trade_zone": "震荡中段不开新仓。",
                                "force_pm_recheck_condition": "若宏观冲击升级，要求 PM 重评。",
                                "next_focus": "观察 BTC 领涨是否持续。",
                            }
                        ],
                    },
                    "decisions": [
                        {
                            "symbol": "BTC",
                            "action": "reduce",
                            "direction": "long",
                            "reason": "Trim into weaker momentum.",
                            "reference_take_profit_condition": "Sell partial strength.",
                            "reference_stop_loss_condition": "If price reclaims highs, stop trimming.",
                            "size_pct_of_exposure_budget": 1.0,
                            "priority": 1,
                            "urgency": "normal",
                            "valid_for_minutes": 10,
                        }
                    ],
                },
            )
            service = ReplayFrontendService(harness.container.memory_assets, harness.container.settings)
            latest = service.latest_agent_state("risk_trader")
            self.assertIn("recent_execution_thoughts", latest)
            self.assertTrue(latest["recent_execution_thoughts"])
            self.assertIn("tactical_brief", latest)
            self.assertIsNotNone(latest["tactical_brief"])
            self.assertEqual(latest["tactical_brief"]["state"], "materialized_map")
            self.assertEqual(latest["tactical_brief"]["coins"][0]["coin"], "BTC")
        finally:
            harness.cleanup()

    def test_latest_agent_state_falls_back_to_last_populated_rt_tactical_map(self) -> None:
        harness = build_test_harness()
        try:
            memory_assets = harness.container.memory_assets
            memory_assets.save_asset(
                asset_type="rt_tactical_map",
                actor_role="risk_trader",
                trace_id="trace-rt-map-1",
                payload={
                    "strategy_key": "strategy_demo:r197",
                    "updated_at_utc": "2026-04-09T06:08:59Z",
                    "refresh_reason": "pm_strategy_revision",
                    "portfolio_posture": "常规推进",
                    "desk_focus": "先沿着 BTC / ETH / SOL 逐步建仓。",
                    "risk_bias": "风险状态正常，可按策略节奏推进。",
                    "next_review_hint": "等待下一轮 RT cadence。",
                    "coins": [
                        {
                            "coin": "BTC",
                            "working_posture": "先观察再推进",
                            "base_case": "沿主趋势推进。",
                            "first_entry_plan": "若当前仍无仓且 BTC active，就先建立最小试探仓。",
                            "preferred_add_condition": "回踩站稳后继续加仓。",
                            "preferred_reduce_condition": "若结构转弱则减仓。",
                            "reference_take_profit_condition": "冲高分批止盈。",
                            "reference_stop_loss_condition": "跌破关键结构止损。",
                            "no_trade_zone": "震荡中段不开新仓。",
                            "force_pm_recheck_condition": "若宏观冲击升级，要求 PM 重评。",
                            "next_focus": "观察 BTC 领涨是否持续。",
                        }
                    ],
                },
            )
            memory_assets.save_asset(
                asset_type="rt_tactical_map",
                actor_role="risk_trader",
                trace_id="trace-rt-map-2",
                payload={
                    "strategy_key": "strategy_demo:r197",
                    "updated_at_utc": "2026-04-09T06:51:29Z",
                    "refresh_reason": "execution_followup",
                    "portfolio_posture": "常规推进",
                    "desk_focus": "执行后跟进回执与风险锁。",
                    "risk_bias": "先观察成交后的波动反馈。",
                    "next_review_hint": "等待 execution follow-up 完整沉淀。",
                    "coins": [],
                },
            )
            service = ReplayFrontendService(harness.container.memory_assets, harness.container.settings)
            latest = service.latest_agent_state("risk_trader")
            self.assertEqual(latest["latest_rt_tactical_map"]["payload"]["refresh_reason"], "execution_followup")
            self.assertEqual(latest["tactical_brief"]["state"], "materialized_map")
            self.assertEqual(latest["tactical_brief"]["coins"][0]["coin"], "BTC")
            self.assertEqual(latest["tactical_brief"]["map_source"], "last_populated_formal_map")
            self.assertIn("最近几轮 RT", latest["tactical_brief"]["map_note"])
        finally:
            harness.cleanup()


if __name__ == "__main__":
    unittest.main()
