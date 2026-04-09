from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openclaw_trader.modules.replay_frontend import ReplayFrontendService
from openclaw_trader.modules.state_memory import StateMemoryRepository, StateMemoryService
from openclaw_trader.shared.infra import SqliteDatabase

from .helpers_v2 import build_test_harness, build_test_settings


class ReplayFrontendServiceTests(unittest.TestCase):
    def test_query_returns_timeline(self) -> None:
        harness = build_test_harness()
        try:
            service = ReplayFrontendService(harness.container.state_memory, harness.container.settings)
            view = service.query()
            self.assertEqual(view.render_hints["mode"], "timeline")
        finally:
            harness.cleanup()

    def test_overview_falls_back_to_threshold_overlay_without_policy_guard(self) -> None:
        with TemporaryDirectory() as tmp:
            sqlite_path = Path(tmp) / "state" / "test.db"
            settings = build_test_settings(sqlite_path)
            state_memory = StateMemoryService(StateMemoryRepository(SqliteDatabase(sqlite_path)))
            state_memory.save_asset(
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
            service = ReplayFrontendService(state_memory, settings)
            overview = service.overview()
            self.assertIsNotNone(overview["risk_overlay"])
            self.assertEqual(overview["risk_overlay"]["state"], "fallback")
            self.assertEqual(overview["risk_overlay"]["observe"]["equity_usd"], "994.0")
            self.assertEqual(overview["risk_overlay"]["reduce"]["equity_usd"], "990.0")
            self.assertEqual(overview["risk_overlay"]["exit"]["equity_usd"], "982.0")


if __name__ == "__main__":
    unittest.main()
