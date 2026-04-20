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
