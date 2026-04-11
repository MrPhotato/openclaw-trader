from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from openclaw_trader.modules.memory_assets import MemoryAssetsRepository, MemoryAssetsService
from openclaw_trader.modules.memory_assets.models import WorkflowStateRef
from openclaw_trader.shared.infra import SqliteDatabase
from openclaw_trader.shared.protocols import EventFactory


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
                    "targets": [],
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
                    "targets": [],
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


if __name__ == "__main__":
    unittest.main()
