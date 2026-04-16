"""Legacy SOL compatibility tests.

SOL was retired from the live forward-running plane. Write paths reject any
strategy/execution that mentions SOL. Read paths, however, must still surface
historical 3-coin payloads that predate the retirement — we never migrate or
rewrite historical memory_assets rows. These tests pin down that contract.

Scope:
1. `memory_assets.latest_asset(asset_type="strategy")` returns raw dicts and
   does NOT run StrategyAsset's 2-target validator, so a legacy 3-coin
   strategy row round-trips intact.
2. `StrategySubmission.model_validate` (the write gate) rejects any payload
   that carries a SOL target.
3. `replay_frontend.latest_agent_state("risk_trader")` passes legacy 3-coin
   rt_tactical_map payloads through without mutating or dropping SOL fields.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from openclaw_trader.modules.agent_gateway.models import StrategySubmission

from tests.helpers_v2 import build_test_harness


LEGACY_THREE_COIN_TARGETS = [
    {
        "symbol": "BTC",
        "state": "active",
        "direction": "long",
        "target_exposure_band_pct": [0.0, 10.0],
        "rt_discretion_band_pct": 5.0,
        "priority": 1,
    },
    {
        "symbol": "ETH",
        "state": "watch",
        "direction": "flat",
        "target_exposure_band_pct": [0.0, 5.0],
        "rt_discretion_band_pct": 0.0,
        "priority": 2,
    },
    {
        "symbol": "SOL",
        "state": "disabled",
        "direction": "flat",
        "target_exposure_band_pct": [0.0, 0.0],
        "rt_discretion_band_pct": 0.0,
        "priority": 3,
    },
]


def _legacy_three_coin_strategy_payload() -> dict:
    now = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
    return {
        "strategy_id": "strategy_legacy_three_coin",
        "strategy_day_utc": now.date().isoformat(),
        "generated_at_utc": now.isoformat(),
        "trigger_type": "scheduled",
        "supersedes_strategy_id": None,
        "revision_number": 1,
        "portfolio_mode": "defensive",
        "target_gross_exposure_band_pct": [0.0, 15.0],
        "portfolio_thesis": "Legacy three-coin thesis.",
        "portfolio_invalidation": "Legacy invalidation condition.",
        "flip_triggers": "Legacy flip trigger.",
        "change_summary": "Legacy change summary.",
        "targets": LEGACY_THREE_COIN_TARGETS,
        "scheduled_rechecks": [],
    }


class LegacySolCompatTests(unittest.TestCase):
    def test_memory_assets_reads_legacy_three_coin_strategy_raw(self) -> None:
        """Historical 3-coin strategy rows must read back intact, validator-free."""
        harness = build_test_harness()
        try:
            legacy_payload = _legacy_three_coin_strategy_payload()
            harness.container.memory_assets.save_asset(
                asset_type="strategy",
                payload=legacy_payload,
                trace_id="trace-legacy-1",
                actor_role="pm",
                group_key=str(legacy_payload["strategy_day_utc"]),
            )

            latest = harness.container.memory_assets.latest_asset(asset_type="strategy")
            self.assertIsNotNone(latest)
            assert latest is not None
            payload = latest["payload"]
            symbols = [str(t["symbol"]).upper() for t in payload["targets"]]
            self.assertEqual(symbols, ["BTC", "ETH", "SOL"])
            sol_entry = next(t for t in payload["targets"] if t["symbol"] == "SOL")
            self.assertEqual(sol_entry["state"], "disabled")
            self.assertEqual(sol_entry["direction"], "flat")
        finally:
            harness.cleanup()

    def test_strategy_submission_rejects_sol_target(self) -> None:
        """The write gate must refuse any submission that names SOL."""
        payload = {
            "portfolio_mode": "normal",
            "target_gross_exposure_band_pct": [0.0, 10.0],
            "portfolio_thesis": "thesis",
            "portfolio_invalidation": "invalidation",
            "flip_triggers": "flip trigger",
            "change_summary": "summary",
            "targets": LEGACY_THREE_COIN_TARGETS,
            "scheduled_rechecks": [],
        }
        with self.assertRaises(ValueError) as ctx:
            StrategySubmission.model_validate(payload)
        message = str(ctx.exception)
        self.assertIn("SOL", message.upper())

    def test_replay_frontend_query_surfaces_legacy_sol_payload(self) -> None:
        """Replay reads for agent state must pass 3-coin tactical maps through."""
        harness = build_test_harness()
        try:
            legacy_map_payload = {
                "strategy_key": "strategy_legacy:r1",
                "updated_at_utc": "2026-03-10T12:05:00Z",
                "refresh_reason": "pm_strategy_revision",
                "portfolio_posture": "常规推进",
                "desk_focus": "先沿着 BTC / ETH / SOL 逐步建仓。",
                "risk_bias": "风险状态正常。",
                "next_review_hint": "等待下一轮 RT cadence。",
                "coins": [
                    {"coin": "BTC", "working_posture": "a", "base_case": "b"},
                    {"coin": "ETH", "working_posture": "a", "base_case": "b"},
                    {"coin": "SOL", "working_posture": "a", "base_case": "b"},
                ],
            }
            harness.container.memory_assets.save_asset(
                asset_type="rt_tactical_map",
                payload=legacy_map_payload,
                trace_id="trace-legacy-rt-map-1",
                actor_role="risk_trader",
            )

            state = harness.container.replay_frontend.latest_agent_state("risk_trader")
            latest_map = state.get("latest_rt_tactical_map")
            self.assertIsNotNone(latest_map, "legacy rt_tactical_map should surface")
            assert latest_map is not None
            latest_map_payload = latest_map["payload"]
            coin_symbols = [str(c["coin"]).upper() for c in latest_map_payload["coins"]]
            self.assertEqual(coin_symbols, ["BTC", "ETH", "SOL"])
            self.assertIn("SOL", latest_map_payload["desk_focus"])
        finally:
            harness.cleanup()


if __name__ == "__main__":
    unittest.main()
