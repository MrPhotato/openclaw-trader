"""Tests for spec 014 (Chief daily macro brief) + spec 015 (PM submit discipline)."""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from openclaw_trader.modules.agent_gateway.service import (
    AgentGatewayService,
    SubmissionTriggerResult,
    SubmissionValidationError,
)
from openclaw_trader.modules.agent_gateway.models import (
    AgentRuntimeLease,
    AgentRuntimePack,
    MacroBriefSubmission,
    StrategyChangeSummary,
    StrategyEvidenceBreakdown,
    StrategySubmission,
    StrategyThesisClaim,
)
from openclaw_trader.modules.memory_assets import (
    MemoryAssetsRepository,
    MemoryAssetsService,
)
from openclaw_trader.modules.memory_assets.models import MacroBriefAsset, StrategyAsset
from openclaw_trader.modules.workflow_orchestrator.macro_brief_trigger import (
    decide_macro_brief_force_refresh,
)
from openclaw_trader.shared.infra import SqliteDatabase

from tests.helpers_v2 import build_test_harness


# ---------------------------------------------------------------------------
# Spec 014: MacroBriefAsset + memory helpers
# ---------------------------------------------------------------------------


def _valid_brief_payload(**overrides: object) -> dict:
    payload: dict = {
        "valid_until_utc": "2026-04-21T13:00:00Z",
        "wake_mode": "daily_macro_brief",
        "regime_tags": {
            "usd_trend": "strong_uptrend",
            "regime_summary": "risk_off_with_crypto_headwind",
        },
        "narrative": "Test regime narrative body describing current crypto headwind.",
        "pm_directives": ["Keep gross band ≤ 20%"],
        "monitoring_triggers": ["DXY > 108"],
        "prior_brief_review": {"verdict": "no_prior"},
        "data_source_snapshot": {"digital_oracle_preset": "chief_regime_read"},
    }
    payload.update(overrides)
    return payload


class MacroBriefAssetTests(unittest.TestCase):
    def test_macro_brief_submission_validates(self) -> None:
        brief = MacroBriefSubmission.model_validate(_valid_brief_payload())
        self.assertEqual(brief.wake_mode, "daily_macro_brief")
        self.assertEqual(brief.prior_brief_review.verdict, "no_prior")

    def test_materialize_macro_brief_round_trip(self) -> None:
        with TemporaryDirectory() as tmp:
            service = MemoryAssetsService(
                MemoryAssetsRepository(SqliteDatabase(Path(tmp) / "state.db"))
            )
            saved = service.materialize_macro_brief(
                trace_id="trace-1",
                authored_payload=_valid_brief_payload(),
            )
            self.assertTrue(saved["brief_id"].startswith("macro_brief"))
            latest = service.latest_macro_brief()
            assert latest is not None
            self.assertEqual(latest["brief_id"], saved["brief_id"])
            fresh = service.get_latest_macro_brief(max_age_hours=48.0)
            assert fresh is not None
            self.assertEqual(fresh["brief_id"], saved["brief_id"])

    def test_macro_brief_asset_requires_narrative(self) -> None:
        with self.assertRaises(Exception):
            MacroBriefAsset.model_validate(
                {
                    "brief_id": "macro_brief_x",
                    "generated_at_utc": datetime.now(UTC).isoformat(),
                    "valid_until_utc": (datetime.now(UTC) + timedelta(hours=36)).isoformat(),
                    "narrative": "",
                    "regime_tags": {},
                    "pm_directives": [],
                    "monitoring_triggers": [],
                    "prior_brief_review": {"verdict": "no_prior"},
                }
            )


# ---------------------------------------------------------------------------
# Spec 014: runtime_pack injection (stale/missing/confidence)
# ---------------------------------------------------------------------------


class MacroBriefRuntimePackTests(unittest.TestCase):
    def test_missing_brief_surfaces_missing_flag(self) -> None:
        harness = build_test_harness()
        try:
            gateway = harness.container.agent_gateway
            payload = gateway._latest_macro_brief_runtime_payload()
            self.assertTrue(payload["missing"])
            self.assertIsNone(payload["brief"])
            self.assertEqual(payload["chief_regime_confidence"], "ok")
        finally:
            harness.cleanup()

    def test_fresh_brief_is_not_stale(self) -> None:
        harness = build_test_harness()
        try:
            memory = harness.container.memory_assets
            memory.materialize_macro_brief(
                trace_id="trace",
                authored_payload={
                    **_valid_brief_payload(
                        valid_until_utc=(datetime.now(UTC) + timedelta(hours=20)).isoformat(),
                    ),
                    "generated_at_utc": datetime.now(UTC).isoformat(),
                },
            )
            payload = harness.container.agent_gateway._latest_macro_brief_runtime_payload()
            self.assertFalse(payload["missing"])
            self.assertFalse(payload["stale"])
            assert payload["age_hours"] is not None
            self.assertLess(payload["age_hours"], 1.0)
        finally:
            harness.cleanup()

    def test_three_falsified_in_a_row_flips_confidence_low(self) -> None:
        harness = build_test_harness()
        try:
            memory = harness.container.memory_assets
            now = datetime.now(UTC)
            for idx in range(3):
                memory.materialize_macro_brief(
                    trace_id=f"trace-{idx}",
                    authored_payload={
                        **_valid_brief_payload(
                            prior_brief_review={"verdict": "falsified"},
                            valid_until_utc=(now + timedelta(hours=36)).isoformat(),
                        ),
                        "generated_at_utc": (now - timedelta(hours=idx)).isoformat(),
                    },
                )
            payload = harness.container.agent_gateway._latest_macro_brief_runtime_payload()
            self.assertEqual(payload["chief_regime_confidence"], "low")
        finally:
            harness.cleanup()


# ---------------------------------------------------------------------------
# Spec 014: event-driven refresh decider
# ---------------------------------------------------------------------------


class MacroBriefForceRefreshTests(unittest.TestCase):
    def test_no_events_means_no_refresh(self) -> None:
        decision = decide_macro_brief_force_refresh(
            news_events=[],
            latest_macro_brief=None,
            recent_forced_refreshes_today=[],
        )
        self.assertFalse(decision.should_refresh)
        self.assertEqual(decision.reason, "no_triggering_event")

    def test_high_impact_monetary_policy_triggers(self) -> None:
        now = datetime.now(UTC)
        decision = decide_macro_brief_force_refresh(
            news_events=[
                {
                    "event_id": "evt-1",
                    "impact_level": "high",
                    "category": "monetary_policy",
                    "detected_at_utc": (now - timedelta(minutes=5)).isoformat(),
                }
            ],
            latest_macro_brief={
                "generated_at_utc": (now - timedelta(hours=2)).isoformat(),
            },
            recent_forced_refreshes_today=[],
            now=now,
        )
        self.assertTrue(decision.should_refresh)
        self.assertEqual(decision.triggered_by_event_id, "evt-1")
        self.assertEqual(decision.event_category, "monetary_policy")

    def test_daily_cap_blocks_third_refresh(self) -> None:
        now = datetime.now(UTC)
        day_start_iso = now.replace(hour=0, minute=30).isoformat()
        decision = decide_macro_brief_force_refresh(
            news_events=[
                {
                    "event_id": "evt-2",
                    "impact_level": "high",
                    "category": "geopolitical",
                    "detected_at_utc": (now - timedelta(minutes=1)).isoformat(),
                }
            ],
            latest_macro_brief={
                "generated_at_utc": (now - timedelta(hours=4)).isoformat(),
            },
            recent_forced_refreshes_today=[
                {"refreshed_at_utc": day_start_iso},
                {"refreshed_at_utc": day_start_iso},
            ],
            daily_force_refresh_cap=2,
            now=now,
        )
        self.assertFalse(decision.should_refresh)
        self.assertEqual(decision.reason, "daily_force_refresh_cap_reached")

    def test_event_seen_by_brief_does_not_retrigger(self) -> None:
        now = datetime.now(UTC)
        brief_time = now - timedelta(minutes=15)
        decision = decide_macro_brief_force_refresh(
            news_events=[
                {
                    "event_id": "evt-3",
                    "impact_level": "high",
                    "category": "macro_data",
                    "detected_at_utc": (now - timedelta(minutes=25)).isoformat(),
                }
            ],
            latest_macro_brief={"generated_at_utc": brief_time.isoformat()},
            recent_forced_refreshes_today=[],
            now=now,
        )
        self.assertFalse(decision.should_refresh)


# ---------------------------------------------------------------------------
# Spec 015: structured thesis + evidence_breakdown validation
# ---------------------------------------------------------------------------


def _structured_strategy_payload(
    *,
    evidence_breakdown: dict | None = None,
    thesis_claims: list[dict] | None = None,
    why_no_external_trigger: str | None = None,
) -> dict:
    breakdown = evidence_breakdown or {
        "price_action_pct": 40,
        "quant_forecast_pct": 35,
        "narrative_pct": 5,
        "regime_pct": 20,
    }
    claims = thesis_claims or [
        {
            "statement": "BTC 3M basis holds.",
            "evidence_type": "price_action",
            "evidence_sources": ["Deribit 5.2%"],
        },
        {
            "statement": "Quant 4h/12h aligned long.",
            "evidence_type": "quant_forecast",
            "evidence_sources": ["BTC:4h p=0.61"],
        },
        {
            "statement": "Chief regime says narrow band.",
            "evidence_type": "regime",
            "evidence_sources": ["latest_macro_brief"],
        },
    ]
    return {
        "portfolio_mode": "normal",
        "target_gross_exposure_band_pct": [0, 20],
        "portfolio_thesis": claims,
        "portfolio_invalidation": "Basis drop",
        "flip_triggers": "BTC sub-72K structural break",
        "change_summary": {
            "headline": "Maintain BTC long bias",
            "evidence_breakdown": breakdown,
            "why_no_external_trigger": why_no_external_trigger,
        },
        "targets": [
            {
                "symbol": "BTC",
                "state": "active",
                "direction": "long",
                "target_exposure_band_pct": [0, 15],
                "rt_discretion_band_pct": 5,
                "priority": 1,
            },
            {
                "symbol": "ETH",
                "state": "watch",
                "direction": "flat",
                "target_exposure_band_pct": [0, 5],
                "rt_discretion_band_pct": 3,
                "priority": 2,
            },
        ],
        "scheduled_rechecks": [],
    }


class StructuredStrategyModelTests(unittest.TestCase):
    def test_structured_submission_validates(self) -> None:
        sub = StrategySubmission.model_validate(_structured_strategy_payload())
        self.assertEqual(len(sub.portfolio_thesis), 3)
        self.assertEqual(sub.change_summary.evidence_breakdown.price_action_pct, 40)

    def test_evidence_breakdown_must_sum_100(self) -> None:
        with self.assertRaises(Exception):
            StrategySubmission.model_validate(
                _structured_strategy_payload(
                    evidence_breakdown={
                        "price_action_pct": 40,
                        "quant_forecast_pct": 35,
                        "narrative_pct": 5,
                        "regime_pct": 10,
                    }
                )
            )

    def test_thesis_variety_required_when_multi_claim(self) -> None:
        claims = [
            {"statement": "A", "evidence_type": "narrative", "evidence_sources": []},
            {"statement": "B", "evidence_type": "narrative", "evidence_sources": []},
        ]
        with self.assertRaises(Exception):
            StrategySubmission.model_validate(
                _structured_strategy_payload(thesis_claims=claims)
            )

    def test_legacy_string_thesis_coerced(self) -> None:
        payload = _structured_strategy_payload()
        payload["portfolio_thesis"] = "legacy single-line thesis"
        payload["change_summary"] = "legacy single-line summary"
        sub = StrategySubmission.model_validate(payload)
        self.assertEqual(len(sub.portfolio_thesis), 1)
        self.assertEqual(sub.portfolio_thesis[0].evidence_type, "mixed")
        self.assertEqual(sub.change_summary.headline, "legacy single-line summary")


# ---------------------------------------------------------------------------
# Spec 015: evaluate_strategy_submission_triggers + hesitation rejection
# ---------------------------------------------------------------------------


class SubmitGateTests(unittest.TestCase):
    def test_cold_start_is_not_internal_reasoning_only(self) -> None:
        harness = build_test_harness()
        try:
            gateway = harness.container.agent_gateway
            lease = _fake_lease()
            result = gateway.evaluate_strategy_submission_triggers(
                lease=lease,
                previous_strategy_asset=None,
            )
            self.assertFalse(result.internal_reasoning_only)
            self.assertIn("cold_start", result.hits)
        finally:
            harness.cleanup()

    def test_owner_push_wake_hits(self) -> None:
        harness = build_test_harness()
        try:
            gateway = harness.container.agent_gateway
            lease = _fake_lease(
                latest_pm_trigger_event={"wake_source": "manual"},
            )
            prev_asset = _fake_prev_strategy_asset(
                generated_at=datetime.now(UTC) - timedelta(hours=2)
            )
            result = gateway.evaluate_strategy_submission_triggers(
                lease=lease,
                previous_strategy_asset=prev_asset,
            )
            self.assertFalse(result.internal_reasoning_only)
            self.assertIn("owner_push", result.hits)
        finally:
            harness.cleanup()

    def test_price_breach_detection(self) -> None:
        harness = build_test_harness()
        try:
            gateway = harness.container.agent_gateway
            lease = _fake_lease(
                current_market_snapshot={
                    "market": {
                        "BTC": {"mark_price": "102.0"},
                        "ETH": {"mark_price": "100.0"},
                    }
                }
            )
            prev_asset = _fake_prev_strategy_asset(
                generated_at=datetime.now(UTC) - timedelta(hours=2),
                submit_market_snapshot={
                    "coins": {
                        "BTC": {"mark_price": 100.0},
                        "ETH": {"mark_price": 100.0},
                    }
                },
            )
            result = gateway.evaluate_strategy_submission_triggers(
                lease=lease,
                previous_strategy_asset=prev_asset,
            )
            self.assertIn("price_breach", result.hits)
            self.assertIn("BTC", result.details["price_breach"]["breaches_pct"])
        finally:
            harness.cleanup()

    def test_quant_flip_detection(self) -> None:
        harness = build_test_harness()
        try:
            gateway = harness.container.agent_gateway
            lease = _fake_lease(
                forecasts={
                    "BTC": {"4h": {"direction": "short", "confidence": 0.6}},
                }
            )
            prev_asset = _fake_prev_strategy_asset(
                generated_at=datetime.now(UTC) - timedelta(hours=1),
                submit_forecast_snapshot={
                    "coins": {
                        "BTC": {"4h": {"direction": "long", "confidence": 0.6}},
                    }
                },
            )
            result = gateway.evaluate_strategy_submission_triggers(
                lease=lease,
                previous_strategy_asset=prev_asset,
            )
            self.assertIn("quant_flip", result.hits)
        finally:
            harness.cleanup()

    def test_price_breach_threshold_honors_settings_override(self) -> None:
        """Spec 015 FR-005: threshold reads from settings.orchestrator.pm_submit_gate_price_breach_pct."""
        harness = build_test_harness()
        try:
            gateway = harness.container.agent_gateway
            # Default 1.5 — a 1.2% move should NOT hit
            lease = _fake_lease(
                current_market_snapshot={
                    "market": {
                        "BTC": {"mark_price": "101.2"},
                        "ETH": {"mark_price": "100.0"},
                    }
                }
            )
            prev_asset = _fake_prev_strategy_asset(
                generated_at=datetime.now(UTC) - timedelta(hours=1),
                submit_market_snapshot={
                    "coins": {
                        "BTC": {"mark_price": 100.0},
                        "ETH": {"mark_price": 100.0},
                    }
                },
            )
            result = gateway.evaluate_strategy_submission_triggers(
                lease=lease,
                previous_strategy_asset=prev_asset,
            )
            self.assertNotIn("price_breach", result.hits)
            # Lower threshold via settings override → same 1.2% move now hits
            harness.container.settings.orchestrator.pm_submit_gate_price_breach_pct = 1.0
            result2 = gateway.evaluate_strategy_submission_triggers(
                lease=lease,
                previous_strategy_asset=prev_asset,
            )
            self.assertIn("price_breach", result2.hits)
            self.assertEqual(result2.details["price_breach"]["threshold_pct"], 1.0)
        finally:
            harness.cleanup()

    def test_no_triggers_marks_internal_reasoning_only(self) -> None:
        harness = build_test_harness()
        try:
            gateway = harness.container.agent_gateway
            lease = _fake_lease(
                current_market_snapshot={
                    "market": {
                        "BTC": {"mark_price": "100.1"},
                        "ETH": {"mark_price": "100.1"},
                    }
                },
                forecasts={
                    "BTC": {"4h": {"direction": "long", "confidence": 0.6}},
                },
            )
            prev_asset = _fake_prev_strategy_asset(
                generated_at=datetime.now(UTC) - timedelta(hours=1),
                submit_market_snapshot={
                    "coins": {
                        "BTC": {"mark_price": 100.0},
                        "ETH": {"mark_price": 100.0},
                    }
                },
                submit_forecast_snapshot={
                    "coins": {
                        "BTC": {"4h": {"direction": "long", "confidence": 0.6}},
                    }
                },
            )
            result = gateway.evaluate_strategy_submission_triggers(
                lease=lease,
                previous_strategy_asset=prev_asset,
            )
            self.assertTrue(result.internal_reasoning_only)
            self.assertEqual(result.hits, [])
        finally:
            harness.cleanup()


class HesitationRejectionTests(unittest.TestCase):
    """submit_strategy rejects internal_reasoning_only without why_no_external_trigger."""

    def test_hesitation_unjustified_rejects_empty_why(self) -> None:
        harness = build_test_harness()
        try:
            gateway = harness.container.agent_gateway
            memory = harness.container.memory_assets
            # Seed a previous strategy with metadata so gate sees no triggers
            self._seed_prev_strategy(memory)
            pack = gateway.pull_pm_runtime_input(trigger_type="pm_main_cron", params={})
            # Compose submission with no external trigger and no why_no_external_trigger
            body = _structured_strategy_payload()
            # Null out why_no_external_trigger
            body["change_summary"]["why_no_external_trigger"] = None
            with self.assertRaises(SubmissionValidationError) as ctx:
                gateway.submit_strategy(input_id=pack.input_id, payload=body)
            self.assertEqual(ctx.exception.error_kind, "hesitation_unjustified")
        finally:
            harness.cleanup()

    def test_hesitation_allowed_with_why(self) -> None:
        harness = build_test_harness()
        try:
            gateway = harness.container.agent_gateway
            memory = harness.container.memory_assets
            self._seed_prev_strategy(memory)
            pack = gateway.pull_pm_runtime_input(trigger_type="pm_main_cron", params={})
            body = _structured_strategy_payload(
                why_no_external_trigger="Quant forecasts reaffirmed but no external hit; committing to hold band.",
            )
            result = gateway.submit_strategy(input_id=pack.input_id, payload=body)
            self.assertTrue(result["internal_reasoning_only"])
        finally:
            harness.cleanup()

    def _seed_prev_strategy(self, memory: MemoryAssetsService) -> None:
        """Seed a previous strategy + stash market/forecast snapshots matching current state.

        The harness's FakeMarketDataProvider always returns BTC mark=100 and
        FakeQuantProvider returns side_4h=long. If the seed's snapshots also
        say BTC mark=100 + BTC:4h=long, the submit-gate will hit 0 triggers.
        """
        # First, make the strategy asset
        payload = _structured_strategy_payload()
        strategy = memory.materialize_strategy_asset(
            trace_id="seed-trace",
            authored_payload=payload,
            trigger_type="manual",
            actor_role="pm",
        )
        # Stash snapshots on the strategy asset metadata so submit-gate can compare
        strategy_id = str(strategy["strategy_id"])
        memory.save_asset(
            asset_type="strategy",
            asset_id=strategy_id,
            payload=strategy,
            trace_id="seed-trace",
            actor_role="pm",
            group_key=str(strategy["strategy_day_utc"]),
            metadata={
                "submit_market_snapshot": {
                    "captured_at_utc": None,
                    "coins": {
                        "BTC": {"mark_price": 100.0},
                        "ETH": {"mark_price": 100.0},
                    },
                },
                "submit_forecast_snapshot": {
                    "coins": {
                        "BTC": {
                            "12h": {"direction": "long", "confidence": 0.72},
                            "4h": {"direction": "long", "confidence": 0.68},
                            "1h": {"direction": "flat", "confidence": 0.51},
                        },
                        "ETH": {
                            "12h": {"direction": "long", "confidence": 0.72},
                            "4h": {"direction": "long", "confidence": 0.68},
                            "1h": {"direction": "flat", "confidence": 0.51},
                        },
                    }
                },
            },
        )


class ChiefRetroDirectiveSupportTests(unittest.TestCase):
    """Chief 2026-04-24 retro identified 4 systemic gaps. Each gap got a
    learning_directive written to the relevant agent's .learnings/*.md.
    Those are agent-self-discipline rules. To make them enforce-able at the
    data layer, four panels were added to the runtime_pack:
    - PM `decision_context.band_revision_streak` (pull/pm)
    - RT `consecutive_holds` (pull/rt)
    - MEA `regime_drift_indicators` (pull/mea)
    - cross-role `theoretical_profit_ceiling` (PM/RT/Chief)
    """

    def _seed_strategies(
        self,
        memory: MemoryAssetsService,
        *,
        bands: list[tuple[float, float]],
        direction: str = "long",
    ) -> list[dict]:
        """Seed N strategies oldest→newest with the given bands."""
        strategies: list[dict] = []
        for band in bands:
            payload = _structured_strategy_payload()
            payload["target_gross_exposure_band_pct"] = list(band)
            for tgt in payload["targets"]:
                if tgt.get("symbol") == "BTC":
                    tgt["state"] = "active"
                    tgt["direction"] = direction
                    break
            strategy = memory.materialize_strategy_asset(
                trace_id=f"seed-{len(strategies)}",
                authored_payload=payload,
                trigger_type="pm_main_cron",
                actor_role="pm",
            )
            strategies.append(strategy)
        return strategies

    def test_band_revision_streak_counts_consecutive_same_band(self) -> None:
        harness = build_test_harness()
        try:
            gateway = harness.container.agent_gateway
            memory = harness.container.memory_assets
            self._seed_strategies(
                memory, bands=[(0, 5), (0, 10), (0, 10), (0, 10)]
            )
            result = gateway._compute_band_revision_streak()
            self.assertEqual(result["count"], 3)
            self.assertEqual(result["current_band"], [0, 10])
            self.assertEqual(result["current_direction"], "long")
            self.assertIn("≥3", result["warning"])
        finally:
            harness.cleanup()

    def test_band_revision_streak_resets_on_band_change(self) -> None:
        harness = build_test_harness()
        try:
            gateway = harness.container.agent_gateway
            memory = harness.container.memory_assets
            self._seed_strategies(memory, bands=[(0, 10), (0, 15)])
            result = gateway._compute_band_revision_streak()
            self.assertEqual(result["count"], 1)
            self.assertEqual(result["current_band"], [0, 15])
            self.assertIsNone(result["warning"])
        finally:
            harness.cleanup()

    def test_band_revision_streak_resets_on_direction_change(self) -> None:
        harness = build_test_harness()
        try:
            gateway = harness.container.agent_gateway
            memory = harness.container.memory_assets
            self._seed_strategies(memory, bands=[(0, 10)], direction="long")
            self._seed_strategies(memory, bands=[(0, 10)], direction="short")
            result = gateway._compute_band_revision_streak()
            self.assertEqual(result["count"], 1)
            self.assertEqual(result["current_direction"], "short")
        finally:
            harness.cleanup()

    def test_consecutive_holds_counts_no_entry_or_scale_batches(self) -> None:
        harness = build_test_harness()
        try:
            gateway = harness.container.agent_gateway
            memory = harness.container.memory_assets
            # 3 hold batches (only `wait`/`hold` actions), then an `add`
            for i, action_set in enumerate(
                [
                    [{"symbol": "BTC", "action": "hold"}],
                    [{"symbol": "BTC", "action": "wait"}],
                    [],  # empty decisions also counts as hold
                    [{"symbol": "BTC", "action": "add"}],  # this one breaks the streak
                ]
            ):
                memory.save_asset(
                    asset_type="execution_batch",
                    actor_role="risk_trader",
                    payload={"decision_id": f"d-{i}", "decisions": action_set},
                )
            result = gateway._compute_consecutive_holds(strategy_payload=None)
            self.assertEqual(
                result["count"], 0,
                "Most recent batch was an `add`, so no current hold streak."
            )
            self.assertEqual(result["last_action"], "entry_or_scale")
        finally:
            harness.cleanup()

    def test_consecutive_holds_warns_when_below_band_midpoint(self) -> None:
        harness = build_test_harness()
        try:
            gateway = harness.container.agent_gateway
            memory = harness.container.memory_assets
            # Two consecutive holds, most recent first when queried
            memory.save_asset(
                asset_type="execution_batch",
                actor_role="risk_trader",
                payload={"decision_id": "d-old", "decisions": [{"symbol": "BTC", "action": "wait"}]},
            )
            memory.save_asset(
                asset_type="execution_batch",
                actor_role="risk_trader",
                payload={"decision_id": "d-new", "decisions": [{"symbol": "BTC", "action": "hold"}]},
            )
            # Seed a portfolio_snapshot showing exposure WAY below band mid (0-10 band → mid=5)
            memory.save_asset(
                asset_type="portfolio_snapshot",
                actor_role="system",
                payload={
                    "total_equity_usd": "1000.0",
                    "total_exposure_usd": "10.0",  # 1% of equity, far below mid=5
                    "positions": [],
                },
            )
            strategy_payload = {"target_gross_exposure_band_pct": [0, 10]}
            result = gateway._compute_consecutive_holds(strategy_payload=strategy_payload)
            self.assertEqual(result["count"], 2)
            self.assertEqual(result["last_action"], "hold")
            self.assertGreater(
                result["gap_to_band_mid_pct"], 0,
                "Exposure (1%) is below band mid (5%), so gap should be positive (room to add)."
            )
            self.assertIn("≥2", result["warning"])
        finally:
            harness.cleanup()

    def test_regime_drift_zero_event_streak(self) -> None:
        harness = build_test_harness()
        try:
            gateway = harness.container.agent_gateway
            memory = harness.container.memory_assets
            # 5 consecutive zero-event news submissions, then an event-bearing one
            for i in range(5):
                memory.save_asset(
                    asset_type="news_submission",
                    actor_role="macro_event_analyst",
                    payload={"submission_id": f"news-zero-{i}", "events": []},
                )
            # event-bearing one is older (saved first → older), but recent_assets
            # returns most-recent first so the streak should still count the
            # 5 zero-event ones at the head
            memory.save_asset(
                asset_type="news_submission",
                actor_role="macro_event_analyst",
                payload={"submission_id": "news-with-event", "events": [{"event_id": "e1"}]},
            )
            # Now the most recent is the event-bearing one, so streak = 0
            result = gateway._compute_regime_drift_indicators()
            self.assertEqual(result["zero_event_streak"], 0)
        finally:
            harness.cleanup()

    def test_regime_drift_zero_event_streak_when_all_recent_are_empty(self) -> None:
        harness = build_test_harness()
        try:
            gateway = harness.container.agent_gateway
            memory = harness.container.memory_assets
            for i in range(4):
                memory.save_asset(
                    asset_type="news_submission",
                    actor_role="macro_event_analyst",
                    payload={"submission_id": f"news-zero-{i}", "events": []},
                )
            result = gateway._compute_regime_drift_indicators()
            self.assertEqual(result["zero_event_streak"], 4)
        finally:
            harness.cleanup()

    def test_theoretical_profit_ceiling_long_direction(self) -> None:
        harness = build_test_harness()
        try:
            gateway = harness.container.agent_gateway
            memory = harness.container.memory_assets
            # Seed today portfolio snapshots: BTC marks 78000 → 78400 → 78200
            # max_favorable_pct (long) = (78400 - 78000) / 78000 = 0.513%
            now = datetime.now(UTC)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            for offset_min, mark in [(0, 78000), (60, 78400), (120, 78200)]:
                memory.save_asset(
                    asset_type="portfolio_snapshot",
                    actor_role="system",
                    payload={
                        "total_equity_usd": "1000.0",
                        "total_exposure_usd": "50.0",  # 5% of equity
                        "positions": [
                            {
                                "coin": "BTC",
                                "side": "long",
                                "raw": {"mark_price": {"value": str(mark)}},
                            }
                        ],
                    },
                )
            strategy_payload = {
                "target_gross_exposure_band_pct": [0, 10],
                "targets": [
                    {"symbol": "BTC", "state": "active", "direction": "long"},
                ],
            }
            result = gateway._compute_theoretical_profit_ceiling(
                strategy_payload=strategy_payload
            )
            self.assertEqual(result["primary_direction"], "long")
            self.assertEqual(result["band_upper_pct_of_budget"], 10.0)
            self.assertEqual(result["discretion_pct_of_budget"], 0.0)
            self.assertEqual(result["envelope_ceiling_pct_of_budget"], 10.0)
            self.assertIsNotNone(result["max_favorable_pct"])
            # Test fixture has no leverage field on position → defaults to 1.
            # band 10% × 1× × 0.513% / 100 = 0.0513% of equity
            self.assertAlmostEqual(
                result["ceiling_at_band_upper_pct_of_equity"], 0.0513, places=3
            )
            # No discretion in fixture → envelope ceiling == band upper
            self.assertAlmostEqual(
                result["ceiling_at_envelope_pct_of_equity"], 0.0513, places=3
            )
            # Current notional 50 / equity 1000 = 5%; PnL = 5% × 0.513% = 0.0257%
            self.assertAlmostEqual(
                result["ceiling_at_current_pct_of_equity"], 0.0257, places=3
            )
            self.assertEqual(result["current_notional_share_of_equity_pct"], 5.0)
        finally:
            harness.cleanup()

    def test_theoretical_profit_ceiling_short_uses_low(self) -> None:
        harness = build_test_harness()
        try:
            gateway = harness.container.agent_gateway
            memory = harness.container.memory_assets
            # Same marks but PM is SHORT → max favorable = (open - low) / open
            for mark in [78000, 78400, 77600]:
                memory.save_asset(
                    asset_type="portfolio_snapshot",
                    actor_role="system",
                    payload={
                        "total_equity_usd": "1000.0",
                        "total_exposure_usd": "50.0",
                        "positions": [
                            {
                                "coin": "BTC",
                                "side": "short",
                                "raw": {"mark_price": {"value": str(mark)}},
                            }
                        ],
                    },
                )
            strategy_payload = {
                "target_gross_exposure_band_pct": [0, 10],
                "targets": [
                    {"symbol": "BTC", "state": "active", "direction": "short"},
                ],
            }
            result = gateway._compute_theoretical_profit_ceiling(
                strategy_payload=strategy_payload
            )
            self.assertEqual(result["primary_direction"], "short")
            # (78000 - 77600) / 78000 = 0.513%
            self.assertAlmostEqual(result["max_favorable_pct"], 0.513, places=2)
        finally:
            harness.cleanup()

    def test_consecutive_holds_envelope_uses_budget_unit_with_discretion(self) -> None:
        """Regression: earlier impl used (notional / equity) for the gap
        computation, which is in % of equity — wrong unit. Strategy contract
        says band/discretion are in % of exposure_budget (= equity ×
        leverage). Verify the gap is computed in the correct unit AND that
        discretion lifts the envelope ceiling above band upper.

        Fixture: equity 1000, leverage 5, notional 100 (= 2% of budget).
        Strategy: band [0, 10] + discretion 10 → envelope ceiling 20% of
        budget. Expected: gap_to_band_mid = 5 - 2 = +3, gap_to_envelope
        ceiling = 20 - 2 = +18.
        """
        harness = build_test_harness()
        try:
            gateway = harness.container.agent_gateway
            memory = harness.container.memory_assets
            memory.save_asset(
                asset_type="portfolio_snapshot",
                actor_role="system",
                payload={
                    "total_equity_usd": "1000.0",
                    "total_exposure_usd": "100.0",
                    "positions": [
                        {
                            "coin": "BTC",
                            "side": "long",
                            "leverage": "5",
                            "raw": {"mark_price": {"value": "78000"}},
                        }
                    ],
                },
            )
            strategy_payload = {
                "target_gross_exposure_band_pct": [0, 10],
                "targets": [
                    {
                        "symbol": "BTC",
                        "state": "active",
                        "direction": "long",
                        "target_exposure_band_pct": [0, 10],
                        "rt_discretion_band_pct": 10,
                    }
                ],
            }
            result = gateway._compute_consecutive_holds(strategy_payload=strategy_payload)
            # Notional 100 / (equity 1000 × leverage 5) = 100 / 5000 = 2%.
            self.assertAlmostEqual(result["current_pct_of_exposure_budget"], 2.0, places=2)
            # Band mid = 5; gap = 5 - 2 = +3 (room to move toward mid).
            self.assertAlmostEqual(result["gap_to_band_mid_pct"], 3.0, places=2)
            # Envelope ceiling = band_hi + discretion = 10 + 10 = 20.
            self.assertAlmostEqual(result["envelope_ceiling_pct_of_budget"], 20.0, places=2)
            # Gap to envelope ceiling = 20 - 2 = +18 (lots of room).
            self.assertAlmostEqual(result["gap_to_envelope_ceiling_pct"], 18.0, places=2)
        finally:
            harness.cleanup()

    def test_theoretical_profit_ceiling_includes_discretion_envelope(self) -> None:
        """Regression: previously projected only band_upper × move%; now must
        also project (band_upper + discretion) × leverage × move% for the
        envelope ceiling RT could realistically achieve.
        """
        harness = build_test_harness()
        try:
            gateway = harness.container.agent_gateway
            memory = harness.container.memory_assets
            for mark in [78000, 78400]:  # +0.513% favorable for long
                memory.save_asset(
                    asset_type="portfolio_snapshot",
                    actor_role="system",
                    payload={
                        "total_equity_usd": "1000.0",
                        "total_exposure_usd": "100.0",
                        "positions": [
                            {
                                "coin": "BTC",
                                "side": "long",
                                "leverage": "5",
                                "raw": {"mark_price": {"value": str(mark)}},
                            }
                        ],
                    },
                )
            strategy_payload = {
                "target_gross_exposure_band_pct": [0, 10],
                "targets": [
                    {
                        "symbol": "BTC",
                        "state": "active",
                        "direction": "long",
                        "rt_discretion_band_pct": 10,
                    }
                ],
            }
            result = gateway._compute_theoretical_profit_ceiling(
                strategy_payload=strategy_payload
            )
            self.assertAlmostEqual(result["max_favorable_pct"], 0.513, places=2)
            self.assertEqual(result["band_upper_pct_of_budget"], 10.0)
            self.assertEqual(result["discretion_pct_of_budget"], 10.0)
            self.assertEqual(result["envelope_ceiling_pct_of_budget"], 20.0)
            # Band-upper-only PnL = 10% × 5x × 0.513% / 100 = 0.2565% of equity
            self.assertAlmostEqual(
                result["ceiling_at_band_upper_pct_of_equity"], 0.2565, places=3
            )
            # Envelope (band + discretion) PnL = 20% × 5x × 0.513% / 100 = 0.513% of equity
            self.assertAlmostEqual(
                result["ceiling_at_envelope_pct_of_equity"], 0.513, places=3
            )
        finally:
            harness.cleanup()

    def test_panels_are_injected_into_runtime_packs(self) -> None:
        """End-to-end: pull/pm, pull/rt, pull/mea each surface their panels."""
        harness = build_test_harness()
        try:
            gateway = harness.container.agent_gateway
            pm_pack = gateway.pull_pm_runtime_input(trigger_type="pm_main_cron", params={})
            self.assertIn("decision_context", pm_pack.payload)
            self.assertIn("band_revision_streak", pm_pack.payload["decision_context"])
            self.assertIn("theoretical_profit_ceiling", pm_pack.payload)

            rt_pack = gateway.pull_rt_runtime_input(trigger_type="rt_event_trigger", params={})
            self.assertIn("consecutive_holds", rt_pack.payload)
            self.assertIn("theoretical_profit_ceiling", rt_pack.payload)

            mea_pack = gateway.pull_mea_runtime_input(trigger_type="mea_2h", params={})
            self.assertIn("regime_drift_indicators", mea_pack.payload)
            drift = mea_pack.payload["regime_drift_indicators"]
            self.assertIn("zero_event_streak", drift)
            self.assertIn("hours_since_last_event", drift)
            self.assertIn("brent_delta_24h_pct", drift)
            self.assertIn("btc_change_pct_24h", drift)
        finally:
            harness.cleanup()


class SubmitGateMetadataPersistenceTests(unittest.TestCase):
    """Regression: before 2026-04-25, materialize_strategy_asset generated an
    internal asset_id that didn't match payload.strategy_id. submit_strategy's
    subsequent `get_asset(strategy_id)` lookup therefore always returned None,
    and the submit_gate / submit_market_snapshot / submit_forecast_snapshot
    metadata update was silently skipped for every PM submit.

    That made the 2/5 snapshot-diff triggers (price_breach, quant_flip) dead:
    each next submit's `_detect_*` functions saw prev_snapshot={} and bailed
    out via `if not prev_coins: return None`. Only new_mea_event / risk_brake
    / owner_push were actually catching external triggers.
    """

    def test_new_strategy_is_lookup_able_by_business_strategy_id(self) -> None:
        with TemporaryDirectory() as tmp:
            service = MemoryAssetsService(
                MemoryAssetsRepository(SqliteDatabase(Path(tmp) / "state.db"))
            )
            strategy = service.materialize_strategy_asset(
                trace_id="trace-1",
                authored_payload=_structured_strategy_payload(),
                trigger_type="pm_main_cron",
                actor_role="pm",
            )
            strategy_id = str(strategy["strategy_id"])
            asset = service.get_asset(strategy_id)
            self.assertIsNotNone(
                asset,
                "materialize_strategy_asset must persist with asset_id=strategy_id so "
                "submit_strategy's get_asset(strategy_id) lookup can find it.",
            )
            self.assertEqual(asset["asset_id"], strategy_id)

    def test_submit_strategy_persists_submit_gate_metadata(self) -> None:
        harness = build_test_harness()
        try:
            gateway = harness.container.agent_gateway
            memory = harness.container.memory_assets
            pack = gateway.pull_pm_runtime_input(trigger_type="pm_main_cron", params={})
            body = _structured_strategy_payload(
                why_no_external_trigger=(
                    "No previous strategy — baseline submit, no external hit expected."
                ),
            )
            result = gateway.submit_strategy(input_id=pack.input_id, payload=body)
            strategy_id = str(result["strategy"]["strategy_id"])

            asset = memory.get_asset(strategy_id)
            self.assertIsNotNone(asset)
            md = dict(asset.get("metadata") or {})
            self.assertIn(
                "submit_gate",
                md,
                "submit_gate metadata must persist on new strategy asset "
                "(next submit's price_breach/quant_flip detectors diff against it).",
            )
            self.assertIn("submit_market_snapshot", md)
            self.assertIn("submit_forecast_snapshot", md)

            gate = md["submit_gate"]
            self.assertIn("hits", gate)
            self.assertIn("internal_reasoning_only", gate)
            self.assertIn("details", gate)
            self.assertIn("coins", md["submit_market_snapshot"])
            self.assertIn("coins", md["submit_forecast_snapshot"])
        finally:
            harness.cleanup()


# ---------------------------------------------------------------------------
# Spec 015: notification + rt_trigger skip on internal_reasoning_only
# ---------------------------------------------------------------------------


class SilentInternalReasoningTests(unittest.TestCase):
    def test_notification_service_skips_internal_reasoning_only(self) -> None:
        harness = build_test_harness()
        try:
            from openclaw_trader.shared.protocols import EventFactory
            notification_service = harness.container.notification_service
            envelope = EventFactory.build(
                trace_id="t-skip",
                event_type="strategy.submitted",
                source_module="agent_gateway",
                entity_type="strategy",
                entity_id="strat-skip",
                payload={
                    "strategy": {"strategy_id": "strat-skip", "internal_reasoning_only": True},
                    "internal_reasoning_only": True,
                },
            )
            events = notification_service.handle_event(envelope)
            self.assertEqual(events, [])
            self.assertEqual(harness.fake_notifier.commands, [])
        finally:
            harness.cleanup()

    def test_notification_service_sends_for_external_revision(self) -> None:
        harness = build_test_harness()
        try:
            from openclaw_trader.shared.protocols import EventFactory
            envelope = EventFactory.build(
                trace_id="t-send",
                event_type="strategy.submitted",
                source_module="agent_gateway",
                entity_type="strategy",
                entity_id="strat-send",
                payload={
                    "strategy": {
                        "strategy_id": "strat-send",
                        "internal_reasoning_only": False,
                        "portfolio_thesis": [{"statement": "...", "evidence_type": "mixed", "evidence_sources": []}],
                        "targets": [],
                    },
                    "internal_reasoning_only": False,
                },
            )
            events = harness.container.notification_service.handle_event(envelope)
            self.assertGreaterEqual(len(events), 1)
        finally:
            harness.cleanup()


# ---------------------------------------------------------------------------
# Spec 015: decision_context aggregator
# ---------------------------------------------------------------------------


class DecisionContextTests(unittest.TestCase):
    def test_pm_pack_has_decision_context_block(self) -> None:
        harness = build_test_harness()
        try:
            gateway = harness.container.agent_gateway
            pack = gateway.pull_pm_runtime_input(trigger_type="pm_main_cron", params={})
            payload = dict(pack.payload)
            self.assertIn("decision_context", payload)
            ctx = payload["decision_context"]
            self.assertIn("price_snapshot", ctx)
            self.assertIn("thesis_price_alignment_flag", ctx)
            # No brief → regime_summary must indicate missing
            self.assertEqual(ctx["regime_summary"], "unknown_brief_missing")
        finally:
            harness.cleanup()

    def test_alignment_flag_diverged_when_long_bias_vs_down_price(self) -> None:
        flag = AgentGatewayService._compute_thesis_price_alignment_flag(
            strategy_payload={
                "targets": [
                    {"symbol": "BTC", "direction": "long", "priority": 1},
                    {"symbol": "ETH", "direction": "flat", "priority": 2},
                ]
            },
            price_snapshot={
                "BTC": {"mark": 100, "change_pct_24h": -2.0},
                "ETH": {"mark": 100, "change_pct_24h": -1.0},
            },
        )
        self.assertEqual(flag, "diverged")

    def test_alignment_flag_aligned_when_same_direction(self) -> None:
        flag = AgentGatewayService._compute_thesis_price_alignment_flag(
            strategy_payload={
                "targets": [{"symbol": "BTC", "direction": "long", "priority": 1}]
            },
            price_snapshot={"BTC": {"mark": 100, "change_pct_24h": 1.5}},
        )
        self.assertEqual(flag, "aligned")

    def test_alignment_flag_unknown_without_target(self) -> None:
        flag = AgentGatewayService._compute_thesis_price_alignment_flag(
            strategy_payload={"targets": []},
            price_snapshot={"BTC": {"mark": 100, "change_pct_24h": 1.5}},
        )
        self.assertEqual(flag, "unknown")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_lease(
    *,
    latest_pm_trigger_event: dict | None = None,
    current_market_snapshot: dict | None = None,
    forecasts: dict | None = None,
) -> AgentRuntimeLease:
    """Build a lightweight AgentRuntimeLease for gate testing."""
    hidden_market = current_market_snapshot or {
        "market": {
            "BTC": {"mark_price": "100.0"},
            "ETH": {"mark_price": "100.0"},
        }
    }
    pack_payload: dict = {
        "forecasts": forecasts or {
            "BTC": {"4h": {"direction": "long", "confidence": 0.6}},
        }
    }
    if latest_pm_trigger_event is not None:
        pack_payload["latest_pm_trigger_event"] = latest_pm_trigger_event
    pack = AgentRuntimePack(
        input_id="input-test",
        trace_id="trace-test",
        agent_role="pm",
        task_kind="strategy",
        trigger_type="pm_main_cron",
        expires_at_utc=datetime.now(UTC) + timedelta(minutes=15),
        payload=pack_payload,
    )
    return AgentRuntimeLease(pack=pack, hidden_payload={"market": hidden_market})


def _fake_prev_strategy_asset(
    *,
    generated_at: datetime,
    submit_market_snapshot: dict | None = None,
    submit_forecast_snapshot: dict | None = None,
) -> dict:
    metadata: dict = {}
    if submit_market_snapshot is not None:
        metadata["submit_market_snapshot"] = submit_market_snapshot
    if submit_forecast_snapshot is not None:
        metadata["submit_forecast_snapshot"] = submit_forecast_snapshot
    return {
        "asset_id": "strat-prev",
        "created_at": generated_at.isoformat(),
        "payload": {
            "strategy_id": "strat-prev",
            "generated_at_utc": generated_at.isoformat(),
        },
        "metadata": metadata,
    }


if __name__ == "__main__":
    unittest.main()
