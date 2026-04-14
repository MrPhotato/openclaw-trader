from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from openclaw_trader.modules.memory_assets import MemoryAssetsRepository, MemoryAssetsService
from openclaw_trader.modules.memory_assets.models import WorkflowStateRef
from openclaw_trader.shared.infra import SqliteDatabase
from openclaw_trader.shared.protocols import EventFactory

from .test_v2_agent_gateway import _valid_strategy_targets


class MemoryAssetsServiceTests(unittest.TestCase):
    def test_workflow_event_and_parameter_roundtrip(self) -> None:
        with TemporaryDirectory() as tmp:
            service = MemoryAssetsService(MemoryAssetsRepository(SqliteDatabase(Path(tmp) / "state.db")))
            workflow = WorkflowStateRef(
                workflow_id="wf-1",
                trace_id="trace-1",
                state="accepted",
                reason="dispatch_once",
                last_transition_at=datetime.now(UTC),
            )
            service.save_workflow("cmd-1", workflow, {"ok": True})
            service.append_event(
                EventFactory.build(
                    trace_id="trace-1",
                    event_type="test.event",
                    source_module="test",
                    entity_type="sample",
                    payload={"ok": True},
                )
            )
            service.save_parameter("alpha", "global", {"value": 1}, operator="tester", reason="unit")
            self.assertIsNotNone(service.get_workflow("trace-1"))
            self.assertEqual(len(service.query_events()), 2)
            self.assertEqual(len(service.list_parameters()), 1)

    def test_materialize_strategy_asset_adds_system_fields_and_revision_chain(self) -> None:
        with TemporaryDirectory() as tmp:
            service = MemoryAssetsService(MemoryAssetsRepository(SqliteDatabase(Path(tmp) / "state.db")))
            first = service.materialize_strategy_asset(
                trace_id="trace-1",
                authored_payload={
                    "portfolio_mode": "normal",
                    "target_gross_exposure_band_pct": [0.0, 5.0],
                    "portfolio_thesis": "thesis-1",
                    "portfolio_invalidation": "invalid-1",
                    "flip_triggers": "flip when multi-horizon structure and macro regime both reverse",
                    "change_summary": "summary-1",
                    "targets": _valid_strategy_targets(),
                    "scheduled_rechecks": [],
                },
                trigger_type="manual",
            )
            second = service.materialize_strategy_asset(
                trace_id="trace-2",
                authored_payload={
                    "portfolio_mode": "defensive",
                    "target_gross_exposure_band_pct": [0.0, 2.0],
                    "portfolio_thesis": "thesis-2",
                    "portfolio_invalidation": "invalid-2",
                    "flip_triggers": "flip when multi-horizon structure and macro regime both reverse",
                    "change_summary": "summary-2",
                    "targets": _valid_strategy_targets(
                        btc_state="watch",
                        btc_direction="flat",
                    ),
                    "scheduled_rechecks": [],
                },
                trigger_type="scheduled_recheck",
            )
            self.assertIn("strategy_id", first)
            self.assertEqual(first["trigger_type"], "manual")
            self.assertEqual(first["revision_number"], 1)
            self.assertIsNone(first["supersedes_strategy_id"])
            self.assertEqual(second["trigger_type"], "scheduled_recheck")
            self.assertEqual(second["revision_number"], 2)
            self.assertEqual(second["supersedes_strategy_id"], first["strategy_id"])
            latest = service.latest_strategy()
            self.assertEqual(latest["payload"]["strategy_id"], second["strategy_id"])

    def test_materialize_news_submission_adds_system_fields(self) -> None:
        with TemporaryDirectory() as tmp:
            service = MemoryAssetsService(MemoryAssetsRepository(SqliteDatabase(Path(tmp) / "state.db")))
            canonical = service.materialize_news_submission(
                trace_id="trace-news",
                authored_payload={
                    "events": [
                        {
                            "event_id": "evt-1",
                            "category": "macro",
                            "summary": "Macro shock.",
                            "impact_level": "high",
                        }
                    ]
                },
            )
            self.assertIn("submission_id", canonical)
            self.assertIn("generated_at_utc", canonical)
            latest = service.latest_asset(asset_type="news_submission")
            self.assertIsNotNone(latest)
            self.assertEqual(latest["payload"]["submission_id"], canonical["submission_id"])

    def test_build_overview_includes_portfolio_risk_overlay(self) -> None:
        with TemporaryDirectory() as tmp:
            service = MemoryAssetsService(MemoryAssetsRepository(SqliteDatabase(Path(tmp) / "state.db")))
            service.save_asset(
                asset_type="policy_guard",
                payload={
                    "coin": "BTC",
                    "portfolio_risk_state": {
                        "state": "observe",
                        "current_equity_usd": "1002.5",
                        "day_peak_equity_usd": "1030",
                        "thresholds": {
                            "observe_drawdown_pct": 1.0,
                            "reduce_drawdown_pct": 2.0,
                            "exit_drawdown_pct": 3.0,
                        },
                    },
                },
                trace_id="trace-policy",
                actor_role="system",
                group_key="BTC",
            )

            overview = service.build_overview()
            self.assertIsNotNone(overview.risk_overlay)
            self.assertEqual(overview.risk_overlay["state"], "observe")
            self.assertEqual(overview.risk_overlay["observe"]["equity_usd"], "1019.7")
            self.assertEqual(overview.risk_overlay["reduce"]["equity_usd"], "1009.4")
            self.assertEqual(overview.risk_overlay["exit"]["equity_usd"], "999.1")

    def test_retro_assets_roundtrip(self) -> None:
        with TemporaryDirectory() as tmp:
            service = MemoryAssetsService(MemoryAssetsRepository(SqliteDatabase(Path(tmp) / "state.db")))
            cycle = service.materialize_retro_cycle_state(
                trace_id="trace-retro",
                authored_payload={
                    "trade_day_utc": "2026-04-14",
                    "state": "case_created",
                    "brief_deadline_utc": "2026-04-14T22:55:00Z",
                    "chief_deadline_utc": "2026-04-14T23:10:00Z",
                    "missing_brief_roles": ["pm", "risk_trader", "macro_event_analyst"],
                },
            )
            retro_case = service.materialize_retro_case(
                trace_id="trace-retro",
                authored_payload={
                    "cycle_id": cycle["cycle_id"],
                    "trigger_type": "daily_retro",
                    "primary_question": "为什么今天没有赚到 1%？",
                    "objective_summary": "拆解 PM、RT、MEA 三个环节的真实贡献。",
                    "challenge_prompts": ["PM 是否过度保守？", "RT 是否执行过慢？"],
                },
            )
            retro_brief = service.materialize_retro_brief(
                trace_id="trace-retro",
                case_id=retro_case["case_id"],
                agent_role="pm",
                cycle_id=cycle["cycle_id"],
                authored_payload={
                    "root_cause": "PM 过度保守。",
                    "cross_role_challenge": "RT 可以更主动。",
                    "self_critique": "flip triggers 写得不够清楚。",
                    "tomorrow_change": "把翻向条件写清楚。",
                },
            )
            directive = service.materialize_learning_directive(
                trace_id="trace-retro",
                case_id=retro_case["case_id"],
                agent_role="pm",
                session_key="agent:pm:main",
                learning_path="/tmp/pm.md",
                cycle_id=cycle["cycle_id"],
                authored_payload={
                    "directive": "把风格切换条件写清楚。",
                    "rationale": "避免 RT 无法执行。",
                },
            )
            latest_cycle = service.latest_retro_cycle_state(trade_day_utc=retro_case["case_day_utc"])
            self.assertIsNotNone(latest_cycle)
            self.assertEqual(latest_cycle["cycle_id"], cycle["cycle_id"])
            latest_case = service.latest_retro_case(case_day_utc=retro_case["case_day_utc"])
            self.assertIsNotNone(latest_case)
            self.assertEqual(latest_case["case_id"], retro_case["case_id"])
            self.assertEqual(latest_case["cycle_id"], cycle["cycle_id"])
            latest_brief = service.latest_retro_brief(case_id=retro_case["case_id"], agent_role="pm")
            self.assertIsNotNone(latest_brief)
            self.assertEqual(latest_brief["brief_id"], retro_brief["brief_id"])
            self.assertEqual(latest_brief["cycle_id"], cycle["cycle_id"])
            self.assertEqual(len(service.get_retro_briefs(case_id=retro_case["case_id"], cycle_id=cycle["cycle_id"])), 1)
            latest_directive = service.latest_learning_directive(agent_role="pm")
            self.assertIsNotNone(latest_directive)
            self.assertEqual(latest_directive["directive_id"], directive["directive_id"])
            self.assertEqual(latest_directive["cycle_id"], cycle["cycle_id"])
            self.assertEqual(len(service.get_learning_directives(case_id=retro_case["case_id"], cycle_id=cycle["cycle_id"])), 1)


if __name__ == "__main__":
    unittest.main()
