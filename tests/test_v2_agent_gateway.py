from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openclaw_trader.modules.agent_gateway import AgentGatewayService, AgentRuntimeInput, SubmissionValidationError
from openclaw_trader.modules.agent_gateway.service import RuntimeInputLeaseError
from openclaw_trader.modules.agent_gateway.adapters import (
    DeterministicAgentRunner,
    DeterministicSessionController,
    OpenClawAgentRunner,
)
from openclaw_trader.modules.agent_gateway.adapters.openclaw import _CommandResult
from openclaw_trader.modules.agent_gateway.models import AgentReply, AgentTask
from openclaw_trader.modules.memory_assets.repository import MemoryAssetsRepository
from openclaw_trader.modules.memory_assets.service import MemoryAssetsService
from openclaw_trader.modules.policy_risk.service import PolicyRiskService
from openclaw_trader.modules.quant_intelligence.service import QuantIntelligenceService
from openclaw_trader.shared.infra import SqliteDatabase
from openclaw_trader.modules.trade_gateway.market_data.service import DataIngestService
from openclaw_trader.modules.news_events.models import NewsDigestEvent

from .helpers_v2 import FakeMarketDataProvider, FakeNewsProvider, FakeQuantProvider, build_test_harness, build_test_settings


def _write_learning_targets(learning_targets: list[dict[str, object]]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for target in learning_targets:
        agent_role = str(target.get("agent_role") or "").strip()
        learning_path = str(target.get("learning_path") or "").strip()
        if not agent_role or not learning_path:
            continue
        learning_summary = f"{agent_role} learned one lesson from retro."
        path = Path(learning_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"- {learning_summary}\n")
        results.append(
            {
                "agent_role": agent_role,
                "learning_updated": True,
                "learning_path": learning_path,
                "learning_summary": learning_summary,
            }
        )
    return results


def _test_strategy_payload() -> dict[str, object]:
    return {
        "strategy_id": "strategy-test-1",
        "strategy_version": "strategy-v1",
        "portfolio_mode": "normal",
        "portfolio_thesis": "test thesis",
        "portfolio_invalidation": "test invalidation",
        "flip_triggers": "flip when multi-horizon structure and macro regime both reverse",
        "change_summary": "test summary",
        "targets": _valid_strategy_targets(),
    }


def _valid_strategy_targets(
    *,
    btc_state: str = "active",
    btc_direction: str = "long",
    btc_band: tuple[float, float] = (0.0, 5.0),
    btc_rt: float = 2.0,
    eth_state: str = "watch",
    eth_direction: str = "flat",
    eth_band: tuple[float, float] = (0.0, 0.0),
    eth_rt: float = 0.0,
    sol_state: str = "watch",
    sol_direction: str = "flat",
    sol_band: tuple[float, float] = (0.0, 0.0),
    sol_rt: float = 0.0,
) -> list[dict[str, object]]:
    return [
        {
            "symbol": "BTC",
            "state": btc_state,
            "direction": btc_direction,
            "target_exposure_band_pct": list(btc_band),
            "rt_discretion_band_pct": btc_rt,
            "priority": 1,
        },
        {
            "symbol": "ETH",
            "state": eth_state,
            "direction": eth_direction,
            "target_exposure_band_pct": list(eth_band),
            "rt_discretion_band_pct": eth_rt,
            "priority": 2,
        },
        {
            "symbol": "SOL",
            "state": sol_state,
            "direction": sol_direction,
            "target_exposure_band_pct": list(sol_band),
            "rt_discretion_band_pct": sol_rt,
            "priority": 3,
        },
    ]


def _valid_strategy_submission_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "portfolio_mode": "normal",
        "target_gross_exposure_band_pct": [0.0, 5.0],
        "portfolio_thesis": "agent first thesis",
        "portfolio_invalidation": "agent first invalidation",
        "flip_triggers": "flip when multi-horizon structure and macro regime both reverse",
        "change_summary": "agent first update",
        "targets": _valid_strategy_targets(),
        "scheduled_rechecks": [],
    }
    payload.update(overrides)
    return payload


def _test_execution_context() -> dict[str, object]:
    return {
        "context_id": "execctx-1",
        "strategy_version": "strategy-v1",
        "coin": "BTC",
        "product_id": "BTC-PERP-INTX",
        "target_bias": "long",
        "target_position_pct_of_exposure_budget": 15.0,
        "max_position_pct_of_exposure_budget": 25.0,
        "rationale": "test",
        "account_snapshot": {
            "current_position_share_pct_of_exposure_budget": 4.0,
        },
        "execution_summary": {
            "state": "flat",
        },
    }


def _seed_runtime_bridge_state(harness, *, trace_id: str = "trace-runtime-bridge") -> dict[str, object]:
    context = harness.container.agent_gateway._collect_bridge_context(
        agent_role="pm",
        trace_id=trace_id,
        trigger_type="pm_main_cron",
    )
    runtime_inputs = harness.container.agent_gateway.build_runtime_inputs(
        trace_id=trace_id,
        market=context["market"],
        policies=context["policies"],
        forecasts=context["forecasts"],
        news_events=context["news"],
        latest_strategy=context["latest_strategy"],
        macro_memory=context["macro_memory"],
    )
    payload = {
        "state_id": "runtime_bridge_state_test",
        "refreshed_at_utc": datetime.now(UTC).isoformat(),
        "refresh_reason": "test_seed",
        "source_timestamps": {},
        "context": {
            "market": context["market"].model_dump(mode="json"),
            "news": [item.model_dump(mode="json") for item in context["news"]],
            "forecasts": {coin: forecast.model_dump(mode="json") for coin, forecast in context["forecasts"].items()},
            "policies": {coin: policy.model_dump(mode="json") for coin, policy in context["policies"].items()},
            "latest_strategy": context["latest_strategy"] or {},
            "macro_memory": list(context["macro_memory"]),
        },
        "runtime_inputs": {
            role: {"task_kind": runtime_input.task_kind, "payload": runtime_input.payload}
            for role, runtime_input in runtime_inputs.items()
        },
    }
    return harness.container.memory_assets.materialize_runtime_bridge_state(
        trace_id=trace_id,
        authored_payload=payload,
        metadata={"refresh_reason": "test_seed"},
    )


class AgentGatewayServiceTests(unittest.TestCase):
    def test_request_execution_decisions_uses_deterministic_runner(self) -> None:
        gateway = AgentGatewayService(
            pm_runner=DeterministicAgentRunner(),
            risk_runner=DeterministicAgentRunner(),
            macro_runner=DeterministicAgentRunner(),
            chief_runner=DeterministicAgentRunner(),
            session_controller=DeterministicSessionController(),
        )
        runtime_input = AgentRuntimeInput(input_id="input-1", agent_role="risk_trader", task_kind="execution")
        decisions = gateway.request_execution_decisions(
            trace_id="trace-1",
            runtime_input=runtime_input,
            execution_contexts=[_test_execution_context()],
        )
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].coin, "BTC")
        self.assertEqual(decisions[0].action, "wait")

    def test_build_runtime_inputs_covers_four_agents(self) -> None:
        gateway = AgentGatewayService(
            pm_runner=DeterministicAgentRunner(),
            risk_runner=DeterministicAgentRunner(),
            macro_runner=DeterministicAgentRunner(),
            chief_runner=DeterministicAgentRunner(),
            session_controller=DeterministicSessionController(),
        )
        market = DataIngestService(FakeMarketDataProvider()).collect(trace_id="trace-1", coins=["BTC"])
        forecasts = QuantIntelligenceService(FakeQuantProvider()).predict_market(market)
        policies = PolicyRiskService(build_test_settings(Path("/tmp") / "state" / "test.db")).evaluate(
            market=market,
            forecasts=forecasts,
            news_events=FakeNewsProvider().latest(),
        )
        strategy = _test_strategy_payload()
        execution_contexts = [_test_execution_context()]
        inputs = gateway.build_runtime_inputs(
            trace_id="trace-1",
            market=market,
            policies=policies,
            forecasts=forecasts,
            strategy=strategy,
            execution_contexts=execution_contexts,
            news_events=FakeNewsProvider().latest(),
        )
        self.assertEqual(set(inputs), {"pm", "risk_trader", "macro_event_analyst", "crypto_chief"})
        self.assertIn("execution_contexts", inputs["risk_trader"].payload)
        self.assertIn("forecasts", inputs["risk_trader"].payload)
        self.assertIn("market", inputs["risk_trader"].payload)
        self.assertIn("news_events", inputs["risk_trader"].payload)
        self.assertIn("product_metadata", inputs["risk_trader"].payload["market"])
        self.assertIn("execution_history", inputs["risk_trader"].payload["market"])
        self.assertNotIn("raw", str(inputs["pm"].payload["market"]))
        pm_history = inputs["pm"].payload["market"]["execution_history"]["BTC"]
        rt_history = inputs["risk_trader"].payload["market"]["execution_history"]["BTC"]
        self.assertLessEqual(len(pm_history["recent_orders"]), 3)
        self.assertLessEqual(len(rt_history["recent_orders"]), 5)
        self.assertIn("summary", pm_history)
        self.assertNotIn("execution_history", inputs["macro_event_analyst"].payload["market"])
        self.assertNotIn("accounts", inputs["macro_event_analyst"].payload["market"])
        pm_series = inputs["pm"].payload["market"]["market_context"]["BTC"]["compressed_price_series"]["24h"]["points"]
        mea_series = inputs["macro_event_analyst"].payload["market"]["market_context"]["BTC"]["compressed_price_series"]["24h"]["points"]
        self.assertLessEqual(len(pm_series), 12)
        self.assertLessEqual(len(mea_series), 8)
        self.assertEqual(inputs["risk_trader"].payload["strategy"]["strategy_version"], strategy["strategy_version"])
        self.assertIn("1h", str(inputs["risk_trader"].payload))
        rt_context = inputs["risk_trader"].payload["execution_contexts"][0]
        self.assertIn("execution_summary", rt_context)
        self.assertNotIn("execution_history", rt_context)
        self.assertNotIn("risk_limits", rt_context)
        self.assertNotIn("position_risk_state", rt_context)
        self.assertNotIn("forecast_snapshot", rt_context)
        self.assertEqual(rt_context["current_position_share_pct_of_exposure_budget"], 4.0)
        self.assertLessEqual(len(inputs["risk_trader"].payload["news_events"]), 5)
        self.assertEqual(inputs["risk_trader"].payload["news_events"][0]["title"], "Macro headline")

    def test_all_runtime_pulls_use_cached_runtime_bridge_state_when_available(self) -> None:
        harness = build_test_harness()
        try:
            _seed_runtime_bridge_state(harness)
            with (
                patch.object(harness.container.market_data, "get_market_overview", side_effect=AssertionError("market_data should not be called")),
                patch.object(harness.container.news_events, "get_latest_news_batch", side_effect=AssertionError("news_events should not be called")),
                patch.object(harness.container.quant_intelligence, "get_latest_forecasts", side_effect=AssertionError("quant should not be called")),
                patch.object(harness.container.memory_assets, "get_latest_strategy", side_effect=AssertionError("strategy should not be called")),
                patch.object(harness.container.memory_assets, "get_asset", side_effect=AssertionError("get_asset should not be called")),
                patch.object(harness.container.memory_assets, "get_macro_memory", side_effect=AssertionError("macro memory should not be called")),
            ):
                pm_pack = harness.container.agent_gateway.pull_pm_runtime_input(trigger_type="pm_main_cron")
                rt_pack = harness.container.agent_gateway.pull_rt_runtime_input(trigger_type="cadence")
                mea_pack = harness.container.agent_gateway.pull_mea_runtime_input(trigger_type="cadence")
                chief_pack = harness.container.agent_gateway.pull_chief_retro_pack(trigger_type="daily_retro")

            self.assertEqual(pm_pack.payload["runtime_bridge_state"]["source"], "cache")
            self.assertEqual(rt_pack.payload["runtime_bridge_state"]["source"], "cache")
            self.assertEqual(mea_pack.payload["runtime_bridge_state"]["source"], "cache")
            self.assertEqual(chief_pack.payload["runtime_bridge_state"]["source"], "cache")
        finally:
            harness.cleanup()

    def test_build_runtime_inputs_compacts_and_ranks_news_for_pm_and_rt(self) -> None:
        gateway = AgentGatewayService(
            pm_runner=DeterministicAgentRunner(),
            risk_runner=DeterministicAgentRunner(),
            macro_runner=DeterministicAgentRunner(),
            chief_runner=DeterministicAgentRunner(),
            session_controller=DeterministicSessionController(),
        )
        market = DataIngestService(FakeMarketDataProvider()).collect(trace_id="trace-1", coins=["BTC"])
        forecasts = QuantIntelligenceService(FakeQuantProvider()).predict_market(market)
        policies = PolicyRiskService(build_test_settings(Path("/tmp") / "state" / "test.db")).evaluate(
            market=market,
            forecasts=forecasts,
            news_events=[],
        )
        strategy = _test_strategy_payload()
        now = datetime.now(UTC)
        events = [
            NewsDigestEvent(
                news_id=f"news-{idx}",
                source="test",
                title=f"medium-{idx}",
                url="https://example.com",
                severity="medium",
                published_at=now - timedelta(hours=idx),
            )
            for idx in range(8)
        ]
        events.extend(
            [
                NewsDigestEvent(
                    news_id="news-high-old",
                    source="test",
                    title="high-old",
                    url="https://example.com",
                    severity="high",
                    published_at=now - timedelta(days=1),
                ),
                NewsDigestEvent(
                    news_id="news-critical-new",
                    source="test",
                    title="critical-new",
                    url="https://example.com",
                    severity="critical",
                    published_at=now,
                ),
            ]
        )
        inputs = gateway.build_runtime_inputs(
            trace_id="trace-1",
            market=market,
            policies=policies,
            forecasts=forecasts,
            strategy=strategy,
            execution_contexts=[_test_execution_context()],
            news_events=events,
        )
        pm_news = inputs["pm"].payload["news_events"]
        rt_news = inputs["risk_trader"].payload["news_events"]
        self.assertLessEqual(len(pm_news), 8)
        self.assertLessEqual(len(rt_news), 5)
        self.assertEqual(pm_news[0]["title"], "critical-new")
        self.assertEqual(rt_news[0]["title"], "critical-new")
        self.assertIn("high-old", [item["title"] for item in pm_news])

    def test_pull_pm_and_rt_runtime_inputs_include_latest_risk_brake_event(self) -> None:
        harness = build_test_harness()
        try:
            harness.container.memory_assets.save_asset(
                asset_type="risk_brake_event",
                actor_role="system",
                payload={
                    "event_id": "risk-brake-1",
                    "detected_at_utc": datetime.now(UTC).isoformat(),
                    "scope": "portfolio",
                    "state": "reduce",
                    "coins": ["BTC"],
                    "lock_mode": "reduce_only",
                    "portfolio_risk_state": {"state": "reduce"},
                    "position_risk_state_by_coin": {"BTC": {"state": "reduce"}},
                    "rt_dispatched": True,
                    "pm_dispatched": True,
                    "system_decision_id": "risk_reduce_decision-1",
                    "execution_result_ids": ["execution_result-1"],
                },
            )

            pm_pack = harness.container.agent_gateway.pull_pm_runtime_input()
            rt_pack = harness.container.agent_gateway.pull_rt_runtime_input()

            self.assertEqual(pm_pack.payload["latest_risk_brake_event"]["scope"], "portfolio")
            self.assertIn("risk_brake_policy", pm_pack.payload)
            self.assertEqual(pm_pack.payload["risk_brake_policy"]["position_peak_drawdown_pct"]["reduce"], 2.8)
            self.assertEqual(pm_pack.payload["risk_brake_policy"]["portfolio_peak_drawdown_pct"]["exit"], 3.2)
            self.assertEqual(pm_pack.payload["risk_brake_policy"]["system_actions"]["reduce"], "system_auto_reduce_then_wake_pm_rt")
            self.assertEqual(rt_pack.payload["latest_risk_brake_event"]["state"], "reduce")
            self.assertEqual(rt_pack.payload["latest_risk_brake_event"]["coins"], ["BTC"])
            self.assertEqual(rt_pack.payload["latest_risk_brake_event"]["lock_mode"], "reduce_only")
            self.assertIn("rt_decision_digest", rt_pack.payload)
            self.assertEqual(rt_pack.payload["rt_decision_digest"]["trigger_summary"]["risk_lock_mode"], "reduce_only")
            self.assertIn("portfolio_summary", rt_pack.payload["rt_decision_digest"])
            self.assertIn("focus_symbols", rt_pack.payload["rt_decision_digest"])
        finally:
            harness.cleanup()

    def test_pull_pm_runtime_input_uses_latest_pm_trigger_event_for_trigger_type(self) -> None:
        harness = build_test_harness()
        try:
            harness.container.memory_assets.save_asset(
                asset_type="pm_trigger_event",
                actor_role="system",
                payload={
                    "event_id": "pm-trigger-1",
                    "detected_at_utc": datetime.now(UTC).isoformat(),
                    "trigger_type": "scheduled_recheck",
                    "reason": "scheduled_recheck",
                    "severity": "normal",
                    "claimable": True,
                    "strategy_id": "strategy-1",
                    "revision_number": 42,
                    "recheck_at_utc": "2026-04-10T03:00:00Z",
                    "scope": "portfolio",
                    "recheck_reason": "Asia session recheck",
                    "scheduled_recheck_key": "strategy-1|2026-04-10T03:00:00Z|portfolio|Asia session recheck",
                    "dispatched": True,
                },
            )
            pack = harness.container.agent_gateway.pull_pm_runtime_input(trigger_type="pm_main_cron")
            self.assertEqual(pack.trigger_type, "scheduled_recheck")
            self.assertEqual(pack.payload["latest_pm_trigger_event"]["reason"], "scheduled_recheck")
            self.assertEqual(pack.payload["trigger_context"]["trigger_type"], "scheduled_recheck")
            claimed_asset = harness.container.memory_assets.latest_asset(asset_type="pm_trigger_event", actor_role="system")
            self.assertIsNotNone(claimed_asset)
            self.assertEqual(claimed_asset["payload"]["claimed_ref"], pack.trace_id)

            second = harness.container.agent_gateway.pull_pm_runtime_input(trigger_type="pm_main_cron")
            self.assertEqual(second.trigger_type, "pm_main_cron")
            self.assertEqual(second.payload["latest_pm_trigger_event"]["trigger_type"], "pm_main_cron")
        finally:
            harness.cleanup()

    def test_pull_pm_runtime_input_ignores_unclaimable_pm_trigger_event(self) -> None:
        harness = build_test_harness()
        try:
            harness.container.memory_assets.save_asset(
                asset_type="pm_trigger_event",
                actor_role="system",
                payload={
                    "event_id": "pm-trigger-skipped",
                    "detected_at_utc": datetime.now(UTC).isoformat(),
                    "trigger_type": "risk_brake",
                    "reason": "portfolio_peak_reduce",
                    "severity": "high",
                    "claimable": False,
                    "dispatched": False,
                    "skipped_reason": "cron_run_failed",
                },
            )
            pack = harness.container.agent_gateway.pull_pm_runtime_input(trigger_type="pm_main_cron")
            self.assertEqual(pack.trigger_type, "pm_main_cron")
            self.assertEqual(pack.payload["latest_pm_trigger_event"]["trigger_type"], "pm_main_cron")
            self.assertEqual(pack.payload["latest_pm_trigger_event"]["wake_source"], "openclaw_cron")
        finally:
            harness.cleanup()

    def test_pull_pm_runtime_input_audits_direct_agent_message(self) -> None:
        harness = build_test_harness()
        try:
            pack = harness.container.agent_gateway.pull_pm_runtime_input(
                trigger_type="agent_message",
                params={
                    "wake_source": "sessions_send",
                    "source_role": "macro_event_analyst",
                    "reason": "high-impact macro alert",
                    "severity": "high",
                },
            )
            self.assertEqual(pack.trigger_type, "agent_message")
            latest_event = dict(pack.payload["latest_pm_trigger_event"])
            self.assertEqual(latest_event["trigger_type"], "agent_message")
            self.assertEqual(latest_event["trigger_category"], "message")
            self.assertEqual(latest_event["wake_source"], "sessions_send")
            self.assertEqual(latest_event["source_role"], "macro_event_analyst")
            self.assertEqual(latest_event["reason"], "high-impact macro alert")
        finally:
            harness.cleanup()

    def test_pull_pm_runtime_input_audits_unspecified_trigger_as_unknown(self) -> None:
        harness = build_test_harness()
        try:
            pack = harness.container.agent_gateway.pull_pm_runtime_input()
            self.assertEqual(pack.trigger_type, "pm_unspecified")
            latest_event = dict(pack.payload["latest_pm_trigger_event"])
            self.assertEqual(latest_event["trigger_type"], "pm_unspecified")
            self.assertEqual(latest_event["trigger_category"], "unknown")
            self.assertEqual(latest_event["wake_source"], "unknown")
            self.assertEqual(latest_event["reason"], "pm_unspecified")
        finally:
            harness.cleanup()

    def test_pull_pm_runtime_input_inherits_recent_agent_message_for_raw_unspecified_pull(self) -> None:
        harness = build_test_harness()
        try:
            first = harness.container.agent_gateway.pull_pm_runtime_input(
                trigger_type="agent_message",
                params={
                    "wake_source": "sessions_send",
                    "source_role": "mea",
                    "reason": "high-impact macro alert",
                    "severity": "high",
                },
            )
            self.assertEqual(first.trigger_type, "agent_message")

            second = harness.container.agent_gateway.pull_pm_runtime_input()
            self.assertEqual(second.trigger_type, "agent_message")
            latest_event = dict(second.payload["latest_pm_trigger_event"])
            self.assertEqual(latest_event["trigger_type"], "agent_message")
            self.assertEqual(latest_event["wake_source"], "sessions_send")
            self.assertEqual(latest_event["source_role"], "mea")
            self.assertEqual(latest_event["reason"], "high-impact macro alert")
            self.assertEqual(
                latest_event["audit_origin"],
                "agent_gateway_pull_fallback_recent_message",
            )
            self.assertTrue(str(latest_event["inherited_from_event_id"]).startswith("pm_trigger"))
        finally:
            harness.cleanup()

    def test_pull_pm_runtime_input_audits_manual_refresh(self) -> None:
        harness = build_test_harness()
        try:
            pack = harness.container.agent_gateway.pull_pm_runtime_input(
                trigger_type="manual",
                params={"reason": "operator rerun after validation failure"},
            )
            self.assertEqual(pack.trigger_type, "manual")
            latest_event = dict(pack.payload["latest_pm_trigger_event"])
            self.assertEqual(latest_event["trigger_type"], "manual")
            self.assertEqual(latest_event["trigger_category"], "manual")
            self.assertEqual(latest_event["wake_source"], "manual")
            self.assertEqual(latest_event["reason"], "operator rerun after validation failure")
        finally:
            harness.cleanup()

    def test_validate_submission_failure_exposes_schema_and_prompt_refs(self) -> None:
        gateway = AgentGatewayService(
            pm_runner=DeterministicAgentRunner(),
            risk_runner=DeterministicAgentRunner(),
            macro_runner=DeterministicAgentRunner(),
            chief_runner=DeterministicAgentRunner(),
            session_controller=DeterministicSessionController(),
        )
        with self.assertRaises(SubmissionValidationError) as raised:
            gateway.validate_submission(
                submission_kind="strategy",
                agent_role="pm",
                trace_id="trace-1",
                payload={"bad": "payload"},
            )
        self.assertEqual(raised.exception.schema_ref, "specs/modules/agent_gateway/contracts/strategy.schema.json")
        self.assertEqual(raised.exception.prompt_ref, "specs/modules/agent_gateway/contracts/strategy.prompt.md")

    def test_validate_strategy_submission_accepts_pm_authored_shape(self) -> None:
        gateway = AgentGatewayService(
            pm_runner=DeterministicAgentRunner(),
            risk_runner=DeterministicAgentRunner(),
            macro_runner=DeterministicAgentRunner(),
            chief_runner=DeterministicAgentRunner(),
            session_controller=DeterministicSessionController(),
        )
        envelope = gateway.validate_submission(
            submission_kind="strategy",
            agent_role="pm",
            trace_id="trace-1",
            payload={
                "portfolio_mode": "normal",
                "target_gross_exposure_band_pct": [0.0, 5.0],
                "portfolio_thesis": "test thesis",
                "portfolio_invalidation": "test invalidation",
                "flip_triggers": "flip when multi-horizon structure and macro regime both reverse",
                "change_summary": "test summary",
                "targets": [
                    {
                        "symbol": "BTC",
                        "state": "active",
                        "direction": "long",
                        "target_exposure_band_pct": [1.0, 2.0],
                        "rt_discretion_band_pct": 1.0,
                        "priority": 1,
                    },
                    {
                        "symbol": "ETH",
                        "state": "watch",
                        "direction": "flat",
                        "target_exposure_band_pct": [0.0, 0.0],
                        "rt_discretion_band_pct": 0.0,
                        "priority": 2,
                    },
                    {
                        "symbol": "SOL",
                        "state": "watch",
                        "direction": "flat",
                        "target_exposure_band_pct": [0.0, 0.0],
                        "rt_discretion_band_pct": 0.0,
                        "priority": 3,
                    },
                ],
                "scheduled_rechecks": [
                    {
                        "recheck_at_utc": "2026-03-20T01:00:00Z",
                        "scope": "portfolio",
                        "reason": "recheck",
                    }
                ],
            },
        )
        self.assertEqual(envelope.submission_kind, "strategy")
        self.assertNotIn("strategy_id", envelope.payload)
        self.assertNotIn("trigger_type", envelope.payload)

    def test_validate_news_submission_accepts_mea_authored_shape(self) -> None:
        gateway = AgentGatewayService(
            pm_runner=DeterministicAgentRunner(),
            risk_runner=DeterministicAgentRunner(),
            macro_runner=DeterministicAgentRunner(),
            chief_runner=DeterministicAgentRunner(),
            session_controller=DeterministicSessionController(),
        )
        envelope = gateway.validate_submission(
            submission_kind="news",
            agent_role="macro_event_analyst",
            trace_id="trace-1",
            payload={
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
        self.assertEqual(envelope.submission_kind, "news")
        self.assertEqual(len(envelope.payload["events"]), 1)
        self.assertNotIn("submission_id", envelope.payload)
        self.assertNotIn("generated_at_utc", envelope.payload)

    def test_validate_execution_submission_rejects_legacy_execution_wrapper(self) -> None:
        gateway = AgentGatewayService(
            pm_runner=DeterministicAgentRunner(),
            risk_runner=DeterministicAgentRunner(),
            macro_runner=DeterministicAgentRunner(),
            chief_runner=DeterministicAgentRunner(),
            session_controller=DeterministicSessionController(),
        )
        with self.assertRaises(SubmissionValidationError) as raised:
            gateway.validate_submission(
                submission_kind="execution",
                agent_role="risk_trader",
                trace_id="trace-1",
                payload={
                    "decision_id": "decision-1",
                    "generated_at_utc": "2026-03-22T00:00:00Z",
                    "trigger_type": "cadence",
                    "execution": {
                        "decisions": [
                            {
                                "symbol": "BTC",
                                "action": "open",
                                "direction": "long",
                                "reason": "test",
                                "size_pct_of_exposure_budget": 2.0,
                                "priority": 1,
                                "urgency": "normal",
                                "valid_for_minutes": 10,
                            }
                        ]
                    },
                },
            )
        self.assertIn("root-level `decisions[]`", raised.exception.errors[0])

    def test_validate_execution_submission_accepts_explicit_empty_decision_batch(self) -> None:
        gateway = AgentGatewayService(
            pm_runner=DeterministicAgentRunner(),
            risk_runner=DeterministicAgentRunner(),
            macro_runner=DeterministicAgentRunner(),
            chief_runner=DeterministicAgentRunner(),
            session_controller=DeterministicSessionController(),
        )
        envelope = gateway.validate_submission(
            submission_kind="execution",
            agent_role="risk_trader",
            trace_id="trace-1",
            payload={
                "decision_id": "decision-1",
                "generated_at_utc": "2026-03-22T00:00:00Z",
                "trigger_type": "cadence",
                "decisions": [],
            },
        )
        self.assertEqual(envelope.payload["decisions"], [])

    def test_validate_execution_submission_accepts_reference_take_profit_condition(self) -> None:
        gateway = AgentGatewayService(
            pm_runner=DeterministicAgentRunner(),
            risk_runner=DeterministicAgentRunner(),
            macro_runner=DeterministicAgentRunner(),
            chief_runner=DeterministicAgentRunner(),
            session_controller=DeterministicSessionController(),
        )
        envelope = gateway.validate_submission(
            submission_kind="execution",
            agent_role="risk_trader",
            trace_id="trace-1",
            payload={
                "decision_id": "decision-1",
                "generated_at_utc": "2026-03-22T00:00:00Z",
                "trigger_type": "cadence",
                "decisions": [
                    {
                        "symbol": "BTC",
                        "action": "add",
                        "direction": "long",
                        "reason": "Momentum remains constructive.",
                        "reference_take_profit_condition": "Trim if BTC tags the upper intraday range and loses momentum.",
                        "reference_stop_loss_condition": "Cut risk if BTC loses the 1h pullback low on expanding sell pressure.",
                        "size_pct_of_exposure_budget": 2.0,
                        "priority": 1,
                        "urgency": "normal",
                        "valid_for_minutes": 15,
                    }
                ],
            },
        )
        self.assertEqual(
            envelope.payload["decisions"][0]["reference_take_profit_condition"],
            "Trim if BTC tags the upper intraday range and loses momentum.",
        )
        self.assertEqual(
            envelope.payload["decisions"][0]["reference_stop_loss_condition"],
            "Cut risk if BTC loses the 1h pullback low on expanding sell pressure.",
        )

    def test_pull_pm_runtime_input_issues_single_runtime_pack_with_lease(self) -> None:
        from .helpers_v2 import build_test_harness

        harness = build_test_harness()
        try:
            pack = harness.container.agent_gateway.pull_pm_runtime_input(
                trigger_type="pm_main_cron",
                params={"cadence_source": "openclaw_cron", "cadence_label": "pm_0100"},
            )
            self.assertEqual(pack.agent_role, "pm")
            self.assertEqual(pack.task_kind, "strategy")
            self.assertEqual(pack.trigger_type, "pm_main_cron")
            self.assertIn("trigger_context", pack.payload)
            lease_asset = harness.container.memory_assets.get_asset(pack.input_id)
            self.assertIsNotNone(lease_asset)
            self.assertEqual(lease_asset["asset_type"], "agent_runtime_lease")
            self.assertEqual(lease_asset["payload"]["status"], "issued")
        finally:
            harness.cleanup()

    def test_pull_rt_runtime_input_includes_recent_execution_thoughts(self) -> None:
        from .helpers_v2 import build_test_harness

        harness = build_test_harness()
        try:
            harness.container.memory_assets.save_asset(
                asset_type="execution_batch",
                trace_id="trace-old",
                actor_role="risk_trader",
                payload={
                    "decision_id": "decision-old-1",
                    "strategy_id": "strategy-old-1",
                    "generated_at_utc": "2026-03-23T00:00:00Z",
                    "decisions": [
                        {
                            "symbol": "BTC",
                            "action": "add",
                            "direction": "long",
                            "reason": "Breakout held and liquidity improved.",
                            "reference_take_profit_condition": "Trim into strength if BTC reaches the 1h range high and stalls.",
                            "reference_stop_loss_condition": "Reduce if BTC loses the 1h pullback low and cannot reclaim it quickly.",
                            "size_pct_of_exposure_budget": 3.0,
                            "urgency": "high",
                        }
                    ],
                },
            )
            harness.container.memory_assets.save_asset(
                asset_type="execution_result",
                trace_id="trace-old",
                actor_role="risk_trader",
                payload={
                    "decision_id": "decision-old-1",
                    "coin": "BTC",
                    "success": True,
                    "technical_failure": False,
                    "message": "filled",
                    "exchange_order_id": "order-old-1",
                    "notional_usd": "125.50",
                    "executed_at": "2026-03-23T00:01:00Z",
                    "fills": [{"price": "68000", "size": "0.0018"}],
                },
            )
            harness.container.memory_assets.save_asset(
                asset_type="rt_trigger_event",
                trace_id="trace-trigger",
                actor_role="system",
                payload={
                    "trigger_id": "rt-trigger-1",
                    "reason": "pm_strategy_update",
                    "severity": "high",
                    "coins": ["BTC"],
                    "dispatched": True,
                },
            )
            pack = harness.container.agent_gateway.pull_rt_runtime_input(
                trigger_type="cadence",
                params={"cadence_source": "openclaw_cron", "cadence_label": "rt_15m"},
            )
            self.assertIn("news_events", pack.payload)
            self.assertTrue(pack.payload["news_events"])
            thoughts = pack.payload["recent_execution_thoughts"]
            self.assertEqual(len(thoughts), 1)
            self.assertEqual(thoughts[0]["symbol"], "BTC")
            self.assertEqual(thoughts[0]["reason"], "Breakout held and liquidity improved.")
            self.assertEqual(
                thoughts[0]["reference_take_profit_condition"],
                "Trim into strength if BTC reaches the 1h range high and stalls.",
            )
            self.assertEqual(
                thoughts[0]["reference_stop_loss_condition"],
                "Reduce if BTC loses the 1h pullback low and cannot reclaim it quickly.",
            )
            self.assertEqual(thoughts[0]["execution_result"]["exchange_order_id"], "order-old-1")
            self.assertEqual(thoughts[0]["execution_result"]["first_fill_price"], "68000")
            self.assertEqual(pack.payload["latest_rt_trigger_event"]["reason"], "pm_strategy_update")
            self.assertEqual(pack.payload["latest_rt_trigger_event"]["coins"], ["BTC"])
            self.assertIn("trigger_delta", pack.payload)
            self.assertIn("standing_tactical_map", pack.payload)
            self.assertIn("execution_submit_defaults", pack.payload)
            self.assertIn("runtime_bridge_state", pack.payload)
            self.assertNotIn("asset_id", pack.payload["latest_rt_trigger_event"])
            self.assertNotIn("trigger_id", pack.payload["latest_rt_trigger_event"])
        finally:
            harness.cleanup()

    def test_pull_rt_runtime_input_returns_compatible_standing_tactical_map(self) -> None:
        from .helpers_v2 import build_test_harness

        harness = build_test_harness()
        try:
            strategy = harness.container.memory_assets.materialize_strategy_asset(
                trace_id="trace-strategy",
                authored_payload={
                    "portfolio_mode": "normal",
                    "target_gross_exposure_band_pct": [20.0, 30.0],
                    "portfolio_thesis": "test strategy",
                    "portfolio_invalidation": "test invalidation",
                    "flip_triggers": "flip when multi-horizon structure and macro regime both reverse",
                    "change_summary": "test summary",
                    "targets": _valid_strategy_targets(),
                    "scheduled_rechecks": [],
                },
                trigger_type="pm_main_cron",
            )
            strategy_key = f"{strategy['strategy_id']}:{strategy['revision_number']}"
            harness.container.memory_assets.materialize_rt_tactical_map(
                trace_id="trace-map",
                strategy_key=strategy_key,
                lock_mode=None,
                authored_payload={
                    "map_refresh_reason": "pm_strategy_revision",
                    "portfolio_posture": "常规推进",
                    "desk_focus": "沿 BTC 主线推进。",
                    "risk_bias": "风险状态正常。",
                    "coins": [
                        {
                            "coin": "BTC",
                            "working_posture": "先观察再推进",
                            "base_case": "沿主趋势推进。",
                            "first_entry_plan": "若当前仍无仓且 BTC 保持 active，就先打 1% 试探仓。",
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

            pack = harness.container.agent_gateway.pull_rt_runtime_input(trigger_type="condition_trigger")
            standing_map = pack.payload["standing_tactical_map"]
            self.assertIsNotNone(standing_map)
            self.assertEqual(standing_map["strategy_key"], strategy_key)
            self.assertEqual(standing_map["coins"][0]["coin"], "BTC")
            self.assertFalse(pack.payload["trigger_delta"]["requires_tactical_map_refresh"])
        finally:
            harness.cleanup()

    def test_pull_rt_runtime_input_requires_refresh_when_strategy_changed_and_map_missing(self) -> None:
        from .helpers_v2 import build_test_harness

        harness = build_test_harness()
        try:
            old_strategy = harness.container.memory_assets.materialize_strategy_asset(
                trace_id="trace-strategy-old",
                authored_payload={
                    "portfolio_mode": "normal",
                    "target_gross_exposure_band_pct": [10.0, 20.0],
                    "portfolio_thesis": "old strategy",
                    "portfolio_invalidation": "old invalidation",
                    "flip_triggers": "flip when multi-horizon structure and macro regime both reverse",
                    "change_summary": "old summary",
                    "targets": _valid_strategy_targets(),
                    "scheduled_rechecks": [],
                },
                trigger_type="pm_main_cron",
            )
            harness.container.memory_assets.materialize_rt_tactical_map(
                trace_id="trace-map-old",
                strategy_key=f"{old_strategy['strategy_id']}:{old_strategy['revision_number']}",
                lock_mode=None,
                authored_payload={
                    "map_refresh_reason": "pm_strategy_revision",
                    "portfolio_posture": "旧图",
                    "desk_focus": "旧图焦点。",
                    "risk_bias": "旧图风险。",
                    "coins": [
                        {
                            "coin": "BTC",
                            "working_posture": "旧图姿态",
                            "base_case": "旧图 base case。",
                            "first_entry_plan": "旧图首笔计划。",
                            "preferred_add_condition": "旧图 add。",
                            "preferred_reduce_condition": "旧图 reduce。",
                            "reference_take_profit_condition": "旧图 tp。",
                            "reference_stop_loss_condition": "旧图 sl。",
                            "no_trade_zone": "旧图 no-trade。",
                            "force_pm_recheck_condition": "旧图 pm。",
                            "next_focus": "旧图 focus。",
                        }
                    ],
                },
            )
            harness.container.memory_assets.materialize_strategy_asset(
                trace_id="trace-strategy-new",
                authored_payload={
                    "portfolio_mode": "defensive",
                    "target_gross_exposure_band_pct": [0.0, 10.0],
                    "portfolio_thesis": "new strategy",
                    "portfolio_invalidation": "new invalidation",
                    "flip_triggers": "flip when multi-horizon structure and macro regime both reverse",
                    "change_summary": "new summary",
                    "targets": _valid_strategy_targets(),
                    "scheduled_rechecks": [],
                },
                trigger_type="pm_main_cron",
            )
            harness.container.memory_assets.save_asset(
                asset_type="rt_trigger_event",
                trace_id="trace-trigger",
                actor_role="system",
                payload={
                    "trigger_id": "rt-trigger-refresh",
                    "detected_at_utc": datetime.now(UTC).isoformat(),
                    "reason": "pm_strategy_update",
                    "severity": "high",
                    "coins": ["BTC"],
                    "dispatched": True,
                },
            )

            pack = harness.container.agent_gateway.pull_rt_runtime_input(trigger_type="condition_trigger")
            self.assertIsNone(pack.payload["standing_tactical_map"])
            self.assertTrue(pack.payload["trigger_delta"]["strategy_changed"])
            self.assertTrue(pack.payload["trigger_delta"]["requires_tactical_map_refresh"])
            self.assertEqual(pack.payload["trigger_delta"]["tactical_map_refresh_reason"], "pm_strategy_revision")
            self.assertEqual(
                pack.payload["rt_decision_digest"]["strategy_summary"]["flip_triggers"],
                "flip when multi-horizon structure and macro regime both reverse",
            )
        finally:
            harness.cleanup()

    def test_pull_rt_runtime_input_requires_refresh_when_map_missing_first_entry_plan(self) -> None:
        from .helpers_v2 import build_test_harness

        harness = build_test_harness()
        try:
            strategy = harness.container.memory_assets.materialize_strategy_asset(
                trace_id="trace-strategy-active-short",
                authored_payload={
                    "portfolio_mode": "defensive",
                    "target_gross_exposure_band_pct": [0.0, 5.0],
                    "portfolio_thesis": "Need immediate defensive short.",
                    "portfolio_invalidation": "Short invalid if BTC reclaims higher timeframe structure.",
                    "flip_triggers": "Flip back long only after higher timeframe reclaim and macro relief.",
                    "change_summary": "Shifted BTC to active short.",
                    "targets": _valid_strategy_targets(
                        btc_state="active",
                        btc_direction="short",
                        btc_band=(0.0, 5.0),
                    ),
                    "scheduled_rechecks": [],
                },
                trigger_type="agent_message",
            )
            harness.container.memory_assets.save_asset(
                asset_type="rt_tactical_map",
                actor_role="risk_trader",
                trace_id="trace-legacy-map",
                payload={
                    "map_id": "rt_tactical_map_legacy_missing_first_entry",
                    "strategy_key": f"{strategy['strategy_id']}:{strategy['revision_number']}",
                    "updated_at_utc": datetime.now(UTC).isoformat(),
                    "refresh_reason": "pm_strategy_revision",
                    "lock_mode": None,
                    "portfolio_posture": "偏空但继续等确认。",
                    "desk_focus": "先等更清楚的 candle close。",
                    "risk_bias": "等确认。",
                    "coins": [
                        {
                            "coin": "BTC",
                            "working_posture": "偏空但等待确认。",
                            "base_case": "先等结构确认。",
                            "preferred_add_condition": "跌破后再加。",
                            "preferred_reduce_condition": "reclaim 关键位后减。",
                            "reference_take_profit_condition": "跌向目标位后分批收。",
                            "reference_stop_loss_condition": "reclaim 关键位后止损。",
                            "no_trade_zone": "中段不动。",
                            "force_pm_recheck_condition": "若 mandate 冲突则要求 PM 重评。",
                            "next_focus": "继续观察。",
                        }
                    ],
                },
            )

            pack = harness.container.agent_gateway.pull_rt_runtime_input(trigger_type="cadence")
            self.assertIsNone(pack.payload["standing_tactical_map"])
            self.assertTrue(pack.payload["trigger_delta"]["requires_tactical_map_refresh"])
            self.assertEqual(pack.payload["trigger_delta"]["map_status"], "missing_first_entry_plan")
            self.assertEqual(pack.payload["trigger_delta"]["missing_first_entry_plan_symbols"], ["BTC"])
        finally:
            harness.cleanup()

    def test_submit_strategy_consumes_runtime_pack_and_rejects_reuse(self) -> None:
        from .helpers_v2 import build_test_harness

        harness = build_test_harness()
        try:
            pack = harness.container.agent_gateway.pull_pm_runtime_input(trigger_type="pm_main_cron")
            result = harness.container.agent_gateway.submit_strategy(
                input_id=pack.input_id,
                payload=_valid_strategy_submission_payload(),
            )
            self.assertEqual(result["strategy"]["trigger_type"], "pm_main_cron")
            lease_asset = harness.container.memory_assets.get_asset(pack.input_id)
            self.assertEqual(lease_asset["payload"]["status"], "consumed")
            with self.assertRaises(RuntimeInputLeaseError) as raised:
                harness.container.agent_gateway.submit_strategy(
                    input_id=pack.input_id,
                    payload=_valid_strategy_submission_payload(
                        portfolio_thesis="duplicate",
                        portfolio_invalidation="duplicate",
                        change_summary="duplicate",
                    ),
                )
            self.assertEqual(raised.exception.reason, "input_already_consumed")
        finally:
            harness.cleanup()

    def test_submit_strategy_emits_trigger_provenance_for_notifications(self) -> None:
        from .helpers_v2 import build_test_harness

        harness = build_test_harness()
        try:
            pack = harness.container.agent_gateway.pull_pm_runtime_input(
                trigger_type="agent_message",
                params={
                    "wake_source": "sessions_send",
                    "source_role": "macro_event_analyst",
                    "reason": "high-impact macro alert",
                    "severity": "high",
                },
            )
            harness.container.agent_gateway.submit_strategy(
                input_id=pack.input_id,
                payload=_valid_strategy_submission_payload(portfolio_mode="defensive"),
            )
            strategy_events = [
                item
                for item in harness.container.memory_assets.query_events()
                if item.get("event_type") == "strategy.submitted"
            ]
            self.assertTrue(strategy_events)
            event_payload = strategy_events[-1]["payload"]
            self.assertEqual(event_payload["trigger_type"], "agent_message")
            self.assertEqual(event_payload["trigger_reason"], "high-impact macro alert")
            self.assertEqual(event_payload["wake_source"], "sessions_send")
            self.assertEqual(event_payload["source_role"], "macro_event_analyst")
            self.assertEqual(
                event_payload["latest_pm_trigger_event"]["trigger_type"],
                "agent_message",
            )
        finally:
            harness.cleanup()

    def test_submit_execution_rejects_wrong_role_input(self) -> None:
        from .helpers_v2 import build_test_harness

        harness = build_test_harness()
        try:
            pack = harness.container.agent_gateway.pull_pm_runtime_input(trigger_type="pm_main_cron")
            with self.assertRaises(RuntimeInputLeaseError) as raised:
                harness.container.agent_gateway.submit_execution(
                    input_id=pack.input_id,
                    payload={
                        "decision_id": "decision-1",
                        "generated_at_utc": "2026-03-21T00:00:00Z",
                        "trigger_type": "manual",
                        "decisions": [],
                    },
                )
            self.assertEqual(raised.exception.reason, "wrong_agent_role")
        finally:
            harness.cleanup()

    def test_submit_execution_accepts_hold_as_noop(self) -> None:
        from .helpers_v2 import build_test_harness

        harness = build_test_harness()
        try:
            pack = harness.container.agent_gateway.pull_rt_runtime_input(trigger_type="cadence")
            result = harness.container.agent_gateway.submit_execution(
                input_id=pack.input_id,
                payload={
                    "decision_id": "decision-hold-1",
                    "generated_at_utc": "2026-03-22T00:00:00Z",
                    "trigger_type": "cadence",
                    "decisions": [
                        {
                            "symbol": "BTC",
                            "action": "hold",
                            "direction": "long",
                            "reason": "keep current position unchanged",
                            "priority": 1,
                            "urgency": "normal",
                            "valid_for_minutes": 10,
                        }
                    ],
                },
                live=True,
            )
            self.assertEqual(result["accepted_count"], 0)
            self.assertEqual(result["plan_count"], 0)
            self.assertEqual(result["execution_results"], [])
        finally:
            harness.cleanup()

    def test_submit_execution_requires_tactical_map_update_when_refresh_is_required(self) -> None:
        from .helpers_v2 import build_test_harness

        harness = build_test_harness()
        try:
            harness.container.memory_assets.materialize_strategy_asset(
                trace_id="trace-strategy-current",
                authored_payload={
                    "portfolio_mode": "normal",
                    "target_gross_exposure_band_pct": [15.0, 25.0],
                    "portfolio_thesis": "current strategy",
                    "portfolio_invalidation": "current invalidation",
                    "flip_triggers": "flip when multi-horizon structure and macro regime both reverse",
                    "change_summary": "current summary",
                    "targets": _valid_strategy_targets(),
                    "scheduled_rechecks": [],
                },
                trigger_type="pm_main_cron",
            )
            harness.container.memory_assets.save_asset(
                asset_type="rt_trigger_event",
                trace_id="trace-trigger-required",
                actor_role="system",
                payload={
                    "trigger_id": "rt-trigger-required",
                    "detected_at_utc": datetime.now(UTC).isoformat(),
                    "reason": "pm_strategy_update",
                    "severity": "high",
                    "coins": ["BTC"],
                    "dispatched": True,
                },
            )

            pack = harness.container.agent_gateway.pull_rt_runtime_input(trigger_type="condition_trigger")
            self.assertTrue(pack.payload["trigger_delta"]["requires_tactical_map_refresh"])
            with self.assertRaises(RuntimeInputLeaseError) as raised:
                harness.container.agent_gateway.submit_execution(
                    input_id=pack.input_id,
                    payload={
                        "decision_id": "decision-missing-map-1",
                        "generated_at_utc": "2026-04-10T00:00:00Z",
                        "trigger_type": "condition_trigger",
                        "decisions": [],
                    },
                    live=True,
                )
            self.assertEqual(raised.exception.reason, "tactical_map_update_required")
        finally:
            harness.cleanup()

    def test_submit_execution_materializes_rt_tactical_map_update(self) -> None:
        from .helpers_v2 import build_test_harness

        harness = build_test_harness()
        try:
            strategy = harness.container.memory_assets.materialize_strategy_asset(
                trace_id="trace-strategy-current",
                authored_payload={
                    "portfolio_mode": "normal",
                    "target_gross_exposure_band_pct": [15.0, 25.0],
                    "portfolio_thesis": "current strategy",
                    "portfolio_invalidation": "current invalidation",
                    "flip_triggers": "flip when multi-horizon structure and macro regime both reverse",
                    "change_summary": "current summary",
                    "targets": _valid_strategy_targets(),
                    "scheduled_rechecks": [],
                },
                trigger_type="pm_main_cron",
            )
            harness.container.memory_assets.save_asset(
                asset_type="rt_trigger_event",
                trace_id="trace-trigger-required",
                actor_role="system",
                payload={
                    "trigger_id": "rt-trigger-required",
                    "detected_at_utc": datetime.now(UTC).isoformat(),
                    "reason": "pm_strategy_update",
                    "severity": "high",
                    "coins": ["BTC"],
                    "dispatched": True,
                },
            )

            pack = harness.container.agent_gateway.pull_rt_runtime_input(trigger_type="condition_trigger")
            result = harness.container.agent_gateway.submit_execution(
                input_id=pack.input_id,
                payload={
                    "decision_id": "decision-map-1",
                    "strategy_id": strategy["strategy_id"],
                    "generated_at_utc": "2026-04-10T00:00:00Z",
                    "trigger_type": "condition_trigger",
                    "tactical_map_update": {
                        "map_refresh_reason": "pm_strategy_revision",
                        "portfolio_posture": "先防守后再找承接。",
                        "desk_focus": "BTC / ETH 先看承接，不追单。",
                        "risk_bias": "headline risk 高时优先保仓位质量。",
                        "next_review_hint": "下一轮先检查 BTC 回踩承接。",
                        "coins": [
                            {
                                "coin": "BTC",
                                "working_posture": "先观察承接再推进",
                                "base_case": "只有回踩站稳后才继续加仓。",
                                "first_entry_plan": "如果当前仍无仓且 BTC 保持 active，就先用 1% 试探仓验证承接。",
                                "preferred_add_condition": "回踩关键位并重新站稳。",
                                "preferred_reduce_condition": "失守 pullback low 时先减仓。",
                                "reference_take_profit_condition": "冲上 1h 上沿但动能衰减时收一部分。",
                                "reference_stop_loss_condition": "跌破关键回踩低点时减仓。",
                                "no_trade_zone": "突破后第一根延伸里不追价。",
                                "force_pm_recheck_condition": "headline risk 升级并破坏结构时要求 PM 重评。",
                                "next_focus": "先看 BTC 回踩后的承接。",
                            }
                        ],
                    },
                    "decisions": [],
                },
                live=True,
            )
            self.assertEqual(result["decision_id"], "decision-map-1")
            latest_map = harness.container.memory_assets.latest_asset(asset_type="rt_tactical_map", actor_role="risk_trader")
            self.assertIsNotNone(latest_map)
            self.assertEqual(latest_map["payload"]["strategy_key"], f"{strategy['strategy_id']}:{strategy['revision_number']}")
            self.assertEqual(latest_map["payload"]["refresh_reason"], "pm_strategy_revision")
            self.assertEqual(latest_map["payload"]["coins"][0]["coin"], "BTC")
        finally:
            harness.cleanup()

    def test_submit_strategy_rejects_partial_targets(self) -> None:
        from .helpers_v2 import build_test_harness

        harness = build_test_harness()
        try:
            pack = harness.container.agent_gateway.pull_pm_runtime_input(trigger_type="pm_main_cron")
            with self.assertRaises(SubmissionValidationError) as raised:
                harness.container.agent_gateway.submit_strategy(
                    input_id=pack.input_id,
                    payload=_valid_strategy_submission_payload(
                        targets=_valid_strategy_targets()[:2],
                    ),
                )
            self.assertIn("targets must contain exactly 3 entries", str(raised.exception.errors[0]))
        finally:
            harness.cleanup()

    def test_submit_execution_rejects_all_wait_when_active_entry_gap_exists(self) -> None:
        from .helpers_v2 import build_test_harness

        harness = build_test_harness()
        try:
            strategy = harness.container.memory_assets.materialize_strategy_asset(
                trace_id="trace-active-short",
                authored_payload={
                    "portfolio_mode": "defensive",
                    "target_gross_exposure_band_pct": [0.0, 5.0],
                    "portfolio_thesis": "Need immediate defensive short.",
                    "portfolio_invalidation": "Short invalid if BTC reclaims higher timeframe structure.",
                    "flip_triggers": "Flip back long only after higher timeframe reclaim and macro relief.",
                    "change_summary": "Shifted BTC to active short.",
                    "targets": _valid_strategy_targets(
                        btc_state="active",
                        btc_direction="short",
                        btc_band=(0.0, 5.0),
                    ),
                    "scheduled_rechecks": [],
                },
                trigger_type="agent_message",
            )
            harness.container.memory_assets.materialize_rt_tactical_map(
                trace_id="trace-map-active-short",
                strategy_key=f"{strategy['strategy_id']}:{strategy['revision_number']}",
                lock_mode=None,
                authored_payload={
                    "map_refresh_reason": "pm_strategy_revision",
                    "portfolio_posture": "防守偏空",
                    "desk_focus": "BTC 先执行首笔 short，而不是继续观望。",
                    "risk_bias": "无锁，可执行。",
                    "coins": [
                        {
                            "coin": "BTC",
                            "working_posture": "首笔 short 应立即建立。",
                            "base_case": "先建最小试探空仓。",
                            "first_entry_plan": "BTC 保持 active short 且当前无仓时，先立即打 1% 试探空仓。",
                            "preferred_add_condition": "跌破结构位后继续加。",
                            "preferred_reduce_condition": "若 reclaim 关键位则减。",
                            "reference_take_profit_condition": "跌至首个目标位分批收。",
                            "reference_stop_loss_condition": "reclaim 关键位则止损。",
                            "no_trade_zone": "没有无意义等待区。",
                            "force_pm_recheck_condition": "若 mandate 与 tape 冲突则要求 PM 重评。",
                            "next_focus": "先打第一笔。",
                        }
                    ],
                },
            )

            pack = harness.container.agent_gateway.pull_rt_runtime_input(trigger_type="cadence")
            with self.assertRaises(SubmissionValidationError) as raised:
                harness.container.agent_gateway.submit_execution(
                    input_id=pack.input_id,
                    payload={
                        "decision_id": "decision-wait-gap-1",
                        "strategy_id": strategy["strategy_id"],
                        "generated_at_utc": "2026-04-13T00:00:00Z",
                        "trigger_type": "cadence",
                        "decisions": [],
                    },
                    live=True,
                )
            self.assertIn("active entry gap detected for BTC", str(raised.exception.errors[0]))
        finally:
            harness.cleanup()

    def test_submit_execution_accepts_pm_recheck_for_active_entry_gap_and_creates_reminder(self) -> None:
        from .helpers_v2 import build_test_harness

        harness = build_test_harness()
        try:
            strategy = harness.container.memory_assets.materialize_strategy_asset(
                trace_id="trace-active-short-recheck",
                authored_payload={
                    "portfolio_mode": "flat",
                    "target_gross_exposure_band_pct": [0.0, 1.0],
                    "portfolio_thesis": "Mandate says short, but gross band is too tight to express cleanly.",
                    "portfolio_invalidation": "Flat stance invalid if PM widens gross band and confirms entry path.",
                    "flip_triggers": "Flip back to active short only after PM resolves the mandate conflict.",
                    "change_summary": "Short target exists but mandate is too constrained.",
                    "targets": _valid_strategy_targets(
                        btc_state="active",
                        btc_direction="short",
                        btc_band=(0.0, 5.0),
                    ),
                    "scheduled_rechecks": [],
                },
                trigger_type="agent_message",
            )
            harness.container.memory_assets.materialize_rt_tactical_map(
                trace_id="trace-map-active-short-recheck",
                strategy_key=f"{strategy['strategy_id']}:{strategy['revision_number']}",
                lock_mode=None,
                authored_payload={
                    "map_refresh_reason": "pm_strategy_revision",
                    "portfolio_posture": "观望但冲突明显",
                    "desk_focus": "要求 PM 重评 mandate。",
                    "risk_bias": "不盲打首笔。",
                    "coins": [
                        {
                            "coin": "BTC",
                            "working_posture": "先升级 PM。",
                            "base_case": "当前 mandate 表达不完整。",
                            "first_entry_plan": "在 PM 澄清前不下首笔，直接要求 PM 重评。",
                            "preferred_add_condition": "PM 澄清后再执行。",
                            "preferred_reduce_condition": "无仓可减。",
                            "reference_take_profit_condition": "N/A",
                            "reference_stop_loss_condition": "N/A",
                            "no_trade_zone": "mandate 冲突时不硬开仓。",
                            "force_pm_recheck_condition": "gross band 与 active short 冲突。",
                            "next_focus": "先让 PM 说清楚。",
                        }
                    ],
                },
            )

            pack = harness.container.agent_gateway.pull_rt_runtime_input(trigger_type="cadence")
            result = harness.container.agent_gateway.submit_execution(
                input_id=pack.input_id,
                payload={
                    "decision_id": "decision-recheck-gap-1",
                    "strategy_id": strategy["strategy_id"],
                    "generated_at_utc": "2026-04-13T00:05:00Z",
                    "trigger_type": "cadence",
                    "pm_recheck_requested": True,
                    "pm_recheck_reason": "BTC is active short but PM still pins gross exposure to 0-1%; RT needs a cleaner mandate before first entry.",
                    "decisions": [],
                },
                live=True,
            )
            self.assertEqual(result["accepted_count"], 0)
            reminder = harness.container.memory_assets.latest_asset(asset_type="direct_reminder")
            self.assertIsNotNone(reminder)
            self.assertEqual(reminder["payload"]["to_agent_role"], "pm")
            self.assertIn("gross exposure to 0-1%", reminder["payload"]["message"])
        finally:
            harness.cleanup()

    def test_submit_execution_rejects_blank_first_entry_plan_for_pending_symbol(self) -> None:
        from .helpers_v2 import build_test_harness

        harness = build_test_harness()
        try:
            strategy = harness.container.memory_assets.materialize_strategy_asset(
                trace_id="trace-active-short-map-refresh",
                authored_payload={
                    "portfolio_mode": "defensive",
                    "target_gross_exposure_band_pct": [0.0, 5.0],
                    "portfolio_thesis": "Need immediate defensive short.",
                    "portfolio_invalidation": "Short invalid if BTC reclaims higher timeframe structure.",
                    "flip_triggers": "Flip back long only after higher timeframe reclaim and macro relief.",
                    "change_summary": "Shifted BTC to active short.",
                    "targets": _valid_strategy_targets(
                        btc_state="active",
                        btc_direction="short",
                        btc_band=(0.0, 5.0),
                    ),
                    "scheduled_rechecks": [],
                },
                trigger_type="agent_message",
            )
            harness.container.memory_assets.save_asset(
                asset_type="rt_trigger_event",
                trace_id="trace-trigger-required-entry-plan",
                actor_role="system",
                payload={
                    "trigger_id": "rt-trigger-required-entry-plan",
                    "detected_at_utc": datetime.now(UTC).isoformat(),
                    "reason": "pm_strategy_update",
                    "severity": "high",
                    "coins": ["BTC"],
                    "dispatched": True,
                },
            )
            pack = harness.container.agent_gateway.pull_rt_runtime_input(trigger_type="condition_trigger")
            with self.assertRaises(SubmissionValidationError) as raised:
                harness.container.agent_gateway.submit_execution(
                    input_id=pack.input_id,
                    payload={
                        "decision_id": "decision-blank-entry-plan-1",
                        "strategy_id": strategy["strategy_id"],
                        "generated_at_utc": "2026-04-13T00:15:00Z",
                        "trigger_type": "condition_trigger",
                        "tactical_map_update": {
                            "map_refresh_reason": "pm_strategy_revision",
                            "portfolio_posture": "偏空执行",
                            "desk_focus": "BTC 首笔要么执行，要么升级。",
                            "risk_bias": "不接受继续空等。",
                            "coins": [
                                {
                                    "coin": "BTC",
                                    "working_posture": "首笔必须明确。",
                                    "base_case": "active short 已经打开，不再接受模糊地图。",
                                    "first_entry_plan": "   ",
                                    "preferred_add_condition": "跌破结构位后继续加。",
                                    "preferred_reduce_condition": "若 reclaim 关键位则减。",
                                    "reference_take_profit_condition": "跌向目标位后分批收。",
                                    "reference_stop_loss_condition": "reclaim 关键位则止损。",
                                    "no_trade_zone": "没有继续空等的 no-trade zone。",
                                    "force_pm_recheck_condition": "若 mandate 与 tape 冲突则要求 PM 重评。",
                                    "next_focus": "先把第一笔打清楚。",
                                }
                            ],
                        },
                        "decisions": [],
                    },
                    live=True,
                )
            self.assertIn("first_entry_plan", str(raised.exception.errors[0]))
        finally:
            harness.cleanup()

    def test_submit_news_materializes_news_and_reminders(self) -> None:
        from .helpers_v2 import build_test_harness

        harness = build_test_harness(news_severity="high")
        try:
            pack = harness.container.agent_gateway.pull_mea_runtime_input(trigger_type="news_batch_ready")
            result = harness.container.agent_gateway.submit_news(
                input_id=pack.input_id,
                payload={
                    "events": [
                        {
                            "event_id": "evt-1",
                            "category": "macro",
                            "summary": "Macro shock",
                            "impact_level": "high",
                        }
                    ]
                },
            )
            self.assertEqual(result["high_impact_count"], 1)
            reminders = harness.container.memory_assets.recent_assets(asset_type="direct_reminder", limit=10)
            self.assertEqual(len(reminders), 2)
        finally:
            harness.cleanup()

    def test_submit_retro_consumes_chief_runtime_pack(self) -> None:
        from .helpers_v2 import build_test_harness

        harness = build_test_harness()
        try:
            prepared = harness.container.agent_gateway.prepare_retro_cycle_from_runtime_bridge(
                trace_id="trace-chief-submit",
                trigger_type="daily_retro",
                force_new_case=True,
            )
            pack = harness.container.agent_gateway.pull_chief_retro_pack(trigger_type="daily_retro")
            result = harness.container.agent_gateway.submit_retro(
                input_id=pack.input_id,
                payload={
                    "case_id": prepared["retro_case"]["case_id"],
                    "meeting_id": "retro-test-1",
                    "round_count": 1,
                    "owner_summary": "Chief retro landed successfully.",
                    "root_cause_ranking": ["PM 过度保守", "RT 过度等待"],
                    "learning_directives": [
                        {
                            "agent_role": "pm",
                            "directive": "把翻向条件写清楚。",
                            "rationale": "避免 RT 无法执行。",
                        }
                    ],
                },
            )
            self.assertEqual(result["owner_summary"], "Chief retro landed successfully.")
            self.assertEqual(result["meeting_id"], "retro-test-1")
            self.assertEqual(result["case_id"], prepared["retro_case"]["case_id"])
            self.assertEqual(result["root_cause_ranking"][0], "PM 过度保守")
            lease_asset = harness.container.memory_assets.get_asset(pack.input_id)
            self.assertEqual(lease_asset["payload"]["status"], "consumed")
            retro_asset = harness.container.memory_assets.latest_asset(asset_type="chief_retro")
            self.assertIsNotNone(retro_asset)
            self.assertEqual(retro_asset["payload"]["owner_summary"], "Chief retro landed successfully.")
            directive_assets = harness.container.memory_assets.get_learning_directives(
                case_id=prepared["retro_case"]["case_id"],
            )
            self.assertEqual(len(directive_assets), 1)
            self.assertEqual(directive_assets[0]["agent_role"], "pm")
        finally:
            harness.cleanup()

    def test_run_pm_submission_retries_once_in_same_session_after_validation_failure(self) -> None:
        class FlakyPmRunner:
            def __init__(self) -> None:
                self.calls: list[AgentTask] = []

            def run(self, task: AgentTask) -> AgentReply:
                self.calls.append(task)
                if len(self.calls) == 1:
                    return AgentReply(
                        task_id=task.task_id,
                        agent_role=task.agent_role,
                        status="completed",
                        payload={"bad": "payload"},
                        meta={"stdout": '{"bad":"payload"}'},
                    )
                return AgentReply(
                    task_id=task.task_id,
                    agent_role=task.agent_role,
                    status="completed",
                    payload={
                        "portfolio_mode": "normal",
                        "target_gross_exposure_band_pct": [0.0, 5.0],
                        "portfolio_thesis": "repaired thesis",
                        "portfolio_invalidation": "repaired invalidation",
                        "flip_triggers": "flip when multi-horizon structure and macro regime both reverse",
                        "change_summary": "repaired summary",
                        "targets": _valid_strategy_targets(),
                        "scheduled_rechecks": [],
                    },
                    meta={"stdout": '{"portfolio_mode":"normal"}'},
                )

        runner = FlakyPmRunner()
        gateway = AgentGatewayService(
            pm_runner=runner,
            risk_runner=DeterministicAgentRunner(),
            macro_runner=DeterministicAgentRunner(),
            chief_runner=DeterministicAgentRunner(),
            session_controller=DeterministicSessionController(),
        )
        envelope = gateway.run_pm_submission(
            trace_id="trace-1",
            runtime_input=AgentRuntimeInput(
                input_id="input-1",
                agent_role="pm",
                task_kind="strategy",
                payload={"trace_id": "trace-1"},
            ),
        )
        self.assertEqual(envelope.submission_kind, "strategy")
        self.assertEqual(len(runner.calls), 2)
        expected_session_id = gateway.session_id_for_role("pm")
        self.assertEqual(runner.calls[0].session_id, expected_session_id)
        self.assertEqual(runner.calls[1].session_id, expected_session_id)
        self.assertEqual(runner.calls[1].payload["mode"], "schema_repair")

    def test_pull_chief_retro_pack_reads_prepared_cycle_without_generating_briefs(self) -> None:
        from .helpers_v2 import build_test_harness

        harness = build_test_harness()
        try:
            prepared = harness.container.agent_gateway.prepare_retro_cycle_from_runtime_bridge(
                trace_id="trace-retro-prep",
                trigger_type="daily_retro",
                force_new_case=True,
            )
            pack = harness.container.agent_gateway.pull_chief_retro_pack(trigger_type="daily_retro")
            self.assertEqual(pack.payload["retro_case"]["case_id"], prepared["retro_case"]["case_id"])
            self.assertEqual(len(pack.payload["retro_briefs"]), 3)
            self.assertEqual(
                {item["agent_role"] for item in pack.payload["retro_briefs"]},
                {"pm", "risk_trader", "macro_event_analyst"},
            )
            self.assertEqual(pack.payload["pending_retro_brief_roles"], [])
            self.assertTrue(pack.payload["retro_ready_for_synthesis"])
            self.assertTrue(pack.payload["learning_targets"])
        finally:
            harness.cleanup()

    def test_pull_chief_retro_pack_reports_pending_briefs_when_cycle_not_prepared(self) -> None:
        from .helpers_v2 import build_test_harness

        harness = build_test_harness()
        try:
            pack = harness.container.agent_gateway.pull_chief_retro_pack(trigger_type="daily_retro")
            self.assertEqual(pack.payload["retro_case"], {})
            self.assertEqual(pack.payload["retro_briefs"], [])
            self.assertEqual(
                pack.payload["pending_retro_brief_roles"],
                ["pm", "risk_trader", "macro_event_analyst"],
            )
            self.assertFalse(pack.payload["retro_ready_for_synthesis"])
        finally:
            harness.cleanup()

    def test_pull_chief_retro_pack_only_keeps_latest_brief_per_role(self) -> None:
        from .helpers_v2 import build_test_harness

        harness = build_test_harness()
        try:
            prepared = harness.container.agent_gateway.prepare_retro_cycle_from_runtime_bridge(
                trace_id="trace-retro-prep-dedup",
                trigger_type="daily_retro",
                force_new_case=True,
            )
            case_id = prepared["retro_case"]["case_id"]
            harness.container.memory_assets.materialize_retro_brief(
                trace_id="trace-retro-overwrite",
                case_id=case_id,
                agent_role="pm",
                authored_payload={
                    "root_cause": "new pm root cause",
                    "cross_role_challenge": "new pm challenge",
                    "self_critique": "new pm self critique",
                    "tomorrow_change": "new pm tomorrow change",
                },
            )
            pack = harness.container.agent_gateway.pull_chief_retro_pack(trigger_type="daily_retro")
            self.assertEqual(len(pack.payload["retro_briefs"]), 3)
            pm_brief = next(item for item in pack.payload["retro_briefs"] if item["agent_role"] == "pm")
            self.assertEqual(pm_brief["root_cause"], "new pm root cause")
        finally:
            harness.cleanup()

    def test_run_chief_retro_synthesis_retries_empty_owner_summary_once(self) -> None:
        class BriefRunner:
            def __init__(self) -> None:
                self.calls: list[AgentTask] = []

            def run(self, task: AgentTask) -> AgentReply:
                self.calls.append(task)
                if task.task_kind == "retro_brief":
                    return AgentReply(
                        task_id=task.task_id,
                        agent_role=task.agent_role,
                        status="completed",
                        payload={
                            "root_cause": f"{task.agent_role} root cause",
                            "cross_role_challenge": f"{task.agent_role} challenge",
                            "self_critique": f"{task.agent_role} self critique",
                            "tomorrow_change": f"{task.agent_role} tomorrow change",
                        },
                    )
                chief_calls = [item for item in self.calls if item.task_kind == "retro"]
                if len(chief_calls) == 1:
                    return AgentReply(
                        task_id=task.task_id,
                        agent_role=task.agent_role,
                        status="completed",
                        payload={
                            "case_id": dict(task.payload.get("retro_case") or {}).get("case_id"),
                            "owner_summary": "   ",
                            "learning_directives": [],
                        },
                    )
                return AgentReply(
                    task_id=task.task_id,
                    agent_role=task.agent_role,
                    status="completed",
                    payload={
                        "case_id": dict(task.payload.get("retro_case") or {}).get("case_id"),
                        "owner_summary": "Retro summary ready.",
                        "learning_directives": [
                            {
                                "agent_role": "pm",
                                "directive": "pm directive",
                                "rationale": "pm rationale",
                            }
                        ],
                    },
                )

        runner = BriefRunner()
        with TemporaryDirectory() as tempdir:
            learning_root = Path(tempdir)
            memory_assets = MemoryAssetsService(MemoryAssetsRepository(SqliteDatabase(Path(tempdir) / "state.db")))
            gateway = AgentGatewayService(
                pm_runner=runner,
                risk_runner=runner,
                macro_runner=runner,
                chief_runner=runner,
                session_controller=DeterministicSessionController(),
                memory_assets=memory_assets,
                learning_path_by_role={
                    "pm": str(learning_root / "pm.md"),
                    "risk_trader": str(learning_root / "rt.md"),
                    "macro_event_analyst": str(learning_root / "mea.md"),
                    "crypto_chief": str(learning_root / "chief.md"),
                },
            )
            runtime_inputs = {
                "pm": AgentRuntimeInput(input_id="input-pm", agent_role="pm", task_kind="strategy", payload={"trace_id": "trace-1"}),
                "risk_trader": AgentRuntimeInput(input_id="input-rt", agent_role="risk_trader", task_kind="execution", payload={"trace_id": "trace-1"}),
                "macro_event_analyst": AgentRuntimeInput(input_id="input-mea", agent_role="macro_event_analyst", task_kind="event_summary", payload={"trace_id": "trace-1"}),
                "crypto_chief": AgentRuntimeInput(
                    input_id="input-chief",
                    agent_role="crypto_chief",
                    task_kind="retro",
                    payload={"trace_id": "trace-1"},
                ),
            }
            prepared = gateway.prepare_retro_cycle(
                trace_id="trace-1",
                runtime_inputs=runtime_inputs,
                trigger_type="daily_retro",
                force_new_case=True,
            )
            payload = gateway.run_chief_retro_synthesis(
                trace_id="trace-1",
                runtime_input=runtime_inputs["crypto_chief"],
                retro_case=dict(prepared["retro_case"]),
                retro_briefs=list(prepared["retro_briefs"]),
            )
            self.assertEqual(payload["owner_summary"], "Retro summary ready.")
            retro_calls = [item for item in runner.calls if item.task_kind == "retro"]
            self.assertEqual(len(retro_calls), 2)
            expected_session_id = gateway.session_id_for_role("crypto_chief")
            self.assertEqual(retro_calls[0].session_id, expected_session_id)
            self.assertEqual(retro_calls[1].session_id, expected_session_id)
            self.assertEqual(retro_calls[0].payload["mode"], "retro_synthesis")
            self.assertEqual(retro_calls[1].payload["mode"], "retro_synthesis_repair")
            self.assertEqual(len([item for item in runner.calls if item.task_kind == "retro_brief"]), 3)

    def test_run_chief_retro_synthesis_persists_case_briefs_and_learning_directives(self) -> None:
        with TemporaryDirectory() as tempdir:
            learning_root = Path(tempdir)
            memory_assets = MemoryAssetsService(MemoryAssetsRepository(SqliteDatabase(Path(tempdir) / "state.db")))
            gateway = AgentGatewayService(
                pm_runner=DeterministicAgentRunner(),
                risk_runner=DeterministicAgentRunner(),
                macro_runner=DeterministicAgentRunner(),
                chief_runner=DeterministicAgentRunner(),
                session_controller=DeterministicSessionController(),
                memory_assets=memory_assets,
                learning_path_by_role={
                    "pm": str(learning_root / "pm.md"),
                    "risk_trader": str(learning_root / "rt.md"),
                    "macro_event_analyst": str(learning_root / "mea.md"),
                    "crypto_chief": str(learning_root / "chief.md"),
                },
            )
            runtime_inputs = {
                "pm": AgentRuntimeInput(input_id="input-pm", agent_role="pm", task_kind="strategy", payload={"trace_id": "trace-meeting"}),
                "risk_trader": AgentRuntimeInput(input_id="input-rt", agent_role="risk_trader", task_kind="execution", payload={"trace_id": "trace-meeting"}),
                "macro_event_analyst": AgentRuntimeInput(input_id="input-mea", agent_role="macro_event_analyst", task_kind="event_summary", payload={"trace_id": "trace-meeting"}),
                "crypto_chief": AgentRuntimeInput(input_id="input-chief", agent_role="crypto_chief", task_kind="retro", payload={"trace_id": "trace-meeting"}),
            }
            prepared = gateway.prepare_retro_cycle(
                trace_id="trace-meeting",
                runtime_inputs=runtime_inputs,
                trigger_type="daily_retro",
                force_new_case=True,
            )
            payload = gateway.run_chief_retro_synthesis(
                trace_id="trace-meeting",
                runtime_input=runtime_inputs["crypto_chief"],
                retro_case=dict(prepared["retro_case"]),
                retro_briefs=list(prepared["retro_briefs"]),
            )
            self.assertTrue(payload["case_id"])
            self.assertEqual(payload["learning_completed"], False)
            self.assertEqual(len(payload["learning_directives"]), 4)
            self.assertEqual(
                {item["agent_role"] for item in payload["learning_directives"]},
                {"pm", "risk_trader", "macro_event_analyst", "crypto_chief"},
            )
            self.assertEqual(len(memory_assets.get_retro_briefs(case_id=payload["case_id"])), 3)
            retro_asset = memory_assets.latest_asset(asset_type="chief_retro")
            self.assertIsNotNone(retro_asset)
            self.assertEqual(retro_asset["payload"]["case_id"], payload["case_id"])
            self.assertEqual(len(memory_assets.get_learning_directives(case_id=payload["case_id"])), 4)
            self.assertEqual(retro_asset["payload"]["learning_directive_ids"], [item["directive_id"] for item in payload["learning_directives"]])

    def test_prepare_retro_cycle_resets_pm_session_once_on_brief_timeout(self) -> None:
        class FlakyPmRunner:
            def __init__(self) -> None:
                self.calls: list[AgentTask] = []

            def run(self, task: AgentTask) -> AgentReply:
                self.calls.append(task)
                if task.task_kind == "retro_brief" and len([item for item in self.calls if item.task_kind == "retro_brief"]) == 1:
                    return AgentReply(
                        task_id=task.task_id,
                        agent_role=task.agent_role,
                        status="needs_escalation",
                        meta={"error_kind": "agent_timeout", "stdout": "", "stderr": ""},
                    )
                return AgentReply(
                    task_id=task.task_id,
                    agent_role=task.agent_role,
                    status="completed",
                    payload={
                        "root_cause": "pm root cause",
                        "cross_role_challenge": "pm challenge",
                        "self_critique": "pm critique",
                        "tomorrow_change": "pm change",
                    },
                )

        class SteadyRetroRunner:
            def __init__(self, agent_role: str) -> None:
                self.agent_role = agent_role
                self.calls: list[AgentTask] = []

            def run(self, task: AgentTask) -> AgentReply:
                self.calls.append(task)
                if task.task_kind == "retro_brief":
                    return AgentReply(
                        task_id=task.task_id,
                        agent_role=task.agent_role,
                        status="completed",
                        payload={
                            "root_cause": f"{task.agent_role} root cause",
                            "cross_role_challenge": f"{task.agent_role} challenge",
                            "self_critique": f"{task.agent_role} critique",
                            "tomorrow_change": f"{task.agent_role} change",
                        },
                    )
                if task.task_kind == "retro":
                    return AgentReply(
                        task_id=task.task_id,
                        agent_role=task.agent_role,
                        status="completed",
                        payload={
                            "case_id": dict(task.payload.get("retro_case") or {}).get("case_id"),
                            "owner_summary": "Retro owner summary ready.",
                            "learning_directives": [],
                        },
                    )
                return AgentReply(task_id=task.task_id, agent_role=task.agent_role, status="completed", payload={})

        class RecordingSessionController:
            def __init__(self) -> None:
                self.resets: list[tuple[str, str, str]] = []

            def reset(self, *, agent_role: str, session_id: str, reset_command: str = "/new") -> dict[str, object]:
                self.resets.append((agent_role, session_id, reset_command))
                return {"success": True, "agent_role": agent_role, "session_id": session_id, "reset_command": reset_command}

        with TemporaryDirectory() as tempdir:
            learning_root = Path(tempdir)
            pm_runner = FlakyPmRunner()
            session_controller = RecordingSessionController()
            gateway = AgentGatewayService(
                pm_runner=pm_runner,
                risk_runner=SteadyRetroRunner("risk_trader"),
                macro_runner=SteadyRetroRunner("macro_event_analyst"),
                chief_runner=SteadyRetroRunner("crypto_chief"),
                session_controller=session_controller,
                memory_assets=MemoryAssetsService(MemoryAssetsRepository(SqliteDatabase(Path(tempdir) / "state.db"))),
                learning_path_by_role={
                    "pm": str(learning_root / "pm.md"),
                    "risk_trader": str(learning_root / "rt.md"),
                    "macro_event_analyst": str(learning_root / "mea.md"),
                    "crypto_chief": str(learning_root / "chief.md"),
                },
            )
            runtime_inputs = {
                "pm": AgentRuntimeInput(input_id="input-pm", agent_role="pm", task_kind="strategy", payload={"trace_id": "trace-retry"}),
                "risk_trader": AgentRuntimeInput(input_id="input-rt", agent_role="risk_trader", task_kind="execution", payload={"trace_id": "trace-retry"}),
                "macro_event_analyst": AgentRuntimeInput(input_id="input-mea", agent_role="macro_event_analyst", task_kind="event_summary", payload={"trace_id": "trace-retry"}),
                "crypto_chief": AgentRuntimeInput(input_id="input-chief", agent_role="crypto_chief", task_kind="retro", payload={"trace_id": "trace-retry"}),
            }
            prepared = gateway.prepare_retro_cycle(
                trace_id="trace-retry",
                runtime_inputs=runtime_inputs,
                trigger_type="daily_retro",
                force_new_case=True,
            )
            self.assertTrue(prepared["retro_case"]["case_id"])
            self.assertEqual(len([item for item in pm_runner.calls if item.task_kind == "retro_brief"]), 2)
            self.assertEqual(len(session_controller.resets), 1)
            self.assertEqual(session_controller.resets[0][0], "pm")
            self.assertEqual(session_controller.resets[0][1], gateway.session_id_for_role("pm"))
            self.assertEqual(len(prepared["retro_briefs"]), 3)

    def test_run_rt_submission_resets_same_session_once_on_input_length_error(self) -> None:
        class ResettableRiskRunner:
            def __init__(self) -> None:
                self.calls: list[AgentTask] = []

            def run(self, task: AgentTask) -> AgentReply:
                self.calls.append(task)
                if len(self.calls) == 1:
                    return AgentReply(
                        task_id=task.task_id,
                        agent_role=task.agent_role,
                        status="needs_escalation",
                        meta={
                            "error_kind": "agent_process_failed",
                            "stderr": "400 InvalidParameter: Range of input length should be [1, 260096]",
                        },
                    )
                return AgentReply(
                    task_id=task.task_id,
                    agent_role=task.agent_role,
                    status="completed",
                    payload={
                        "decision_id": "decision-1",
                        "strategy_id": "strategy-1",
                        "generated_at_utc": "2026-03-20T01:00:00Z",
                        "trigger_type": "manual",
                        "decisions": [],
                    },
                    meta={"stdout": '{"decision_id":"decision-1","generated_at_utc":"2026-03-20T01:00:00Z","trigger_type":"manual","decisions": []}'},
                )

        class RecordingSessionController:
            def __init__(self) -> None:
                self.resets: list[tuple[str, str, str]] = []

            def reset(self, *, agent_role: str, session_id: str, reset_command: str = "/new") -> dict[str, object]:
                self.resets.append((agent_role, session_id, reset_command))
                return {"success": True, "agent_role": agent_role, "session_id": session_id, "reset_command": reset_command}

        runner = ResettableRiskRunner()
        session_controller = RecordingSessionController()
        gateway = AgentGatewayService(
            pm_runner=DeterministicAgentRunner(),
            risk_runner=runner,
            macro_runner=DeterministicAgentRunner(),
            chief_runner=DeterministicAgentRunner(),
            session_controller=session_controller,
        )
        envelope = gateway.run_rt_submission(
            trace_id="trace-1",
            runtime_input=AgentRuntimeInput(
                input_id="input-1",
                agent_role="risk_trader",
                task_kind="execution",
                payload={"trace_id": "trace-1"},
            ),
        )
        self.assertEqual(envelope.submission_kind, "execution")
        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(len(session_controller.resets), 1)
        self.assertEqual(session_controller.resets[0][0], "risk_trader")
        expected_session_id = gateway.session_id_for_role("risk_trader")
        self.assertEqual(session_controller.resets[0][1], expected_session_id)

    def test_run_rt_submission_resets_same_session_once_on_agent_timeout(self) -> None:
        class TimeoutThenSuccessRiskRunner:
            def __init__(self) -> None:
                self.calls: list[AgentTask] = []

            def run(self, task: AgentTask) -> AgentReply:
                self.calls.append(task)
                if len(self.calls) == 1:
                    return AgentReply(
                        task_id=task.task_id,
                        agent_role=task.agent_role,
                        status="needs_escalation",
                        meta={
                            "error_kind": "agent_timeout",
                            "stdout": "",
                            "stderr": "",
                        },
                    )
                return AgentReply(
                    task_id=task.task_id,
                    agent_role=task.agent_role,
                    status="completed",
                    payload={
                        "decision_id": "decision-timeout-recovered",
                        "strategy_id": "strategy-1",
                        "generated_at_utc": "2026-03-20T01:00:00Z",
                        "trigger_type": "manual",
                        "decisions": [],
                    },
                    meta={"stdout": '{"decision_id":"decision-timeout-recovered","generated_at_utc":"2026-03-20T01:00:00Z","trigger_type":"manual","decisions": []}'},
                )

        class RecordingSessionController:
            def __init__(self) -> None:
                self.resets: list[tuple[str, str, str]] = []

            def reset(self, *, agent_role: str, session_id: str, reset_command: str = "/new") -> dict[str, object]:
                self.resets.append((agent_role, session_id, reset_command))
                return {"success": True, "agent_role": agent_role, "session_id": session_id, "reset_command": reset_command}

        runner = TimeoutThenSuccessRiskRunner()
        session_controller = RecordingSessionController()
        gateway = AgentGatewayService(
            pm_runner=DeterministicAgentRunner(),
            risk_runner=runner,
            macro_runner=DeterministicAgentRunner(),
            chief_runner=DeterministicAgentRunner(),
            session_controller=session_controller,
        )
        envelope = gateway.run_rt_submission(
            trace_id="trace-1",
            runtime_input=AgentRuntimeInput(
                input_id="input-1",
                agent_role="risk_trader",
                task_kind="execution",
                payload={"trace_id": "trace-1"},
            ),
        )
        self.assertEqual(envelope.submission_kind, "execution")
        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(len(session_controller.resets), 1)
        expected_session_id = gateway.session_id_for_role("risk_trader")
        self.assertEqual(session_controller.resets[0][1], expected_session_id)


class OpenClawAgentRunnerTests(unittest.TestCase):
    @patch("openclaw_trader.modules.agent_gateway.adapters.openclaw._run_command")
    def test_runner_uses_json_session_and_extracts_fenced_payload(self, run_mock) -> None:
        run_mock.return_value = _CommandResult(
            returncode=0,
            stdout='noise\n{"final":{"content":"```json\\n{\\"portfolio_mode\\":\\"normal\\",\\"target_gross_exposure_band_pct\\":[0,1],\\"portfolio_thesis\\":\\"t\\",\\"portfolio_invalidation\\":\\"i\\",\\"change_summary\\":\\"c\\",\\"targets\\":[],\\"scheduled_rechecks\\":[] }\\n```"}}\n',
            stderr="",
        )
        runner = OpenClawAgentRunner("pm", timeout_seconds=42)
        reply = runner.run(
            AgentTask(
                task_id="task-1",
                agent_role="pm",
                task_kind="strategy",
                input_id="input-1",
                trace_id="trace-1",
                session_id="pm-session",
                payload={"trace_id": "trace-1"},
            )
        )
        self.assertEqual(reply.status, "completed")
        self.assertEqual(reply.payload["portfolio_mode"], "normal")
        command = run_mock.call_args.args[0]
        called = run_mock.call_args.kwargs
        self.assertIn("--session-id", command)
        self.assertIn("pm-session", command)
        self.assertIn("--json", command)
        self.assertIn("--timeout", command)
        self.assertEqual(called["timeout_seconds"], 47)

    @patch("openclaw_trader.modules.agent_gateway.adapters.openclaw._run_command")
    def test_runner_extracts_nested_payload_text_for_mea(self, run_mock) -> None:
        run_mock.return_value = _CommandResult(
            returncode=0,
            stdout='{"result":{"payloads":[{"text":"{\\"events\\":[{\\"event_id\\":\\"evt-1\\",\\"category\\":\\"macro\\",\\"summary\\":\\"Macro shock.\\",\\"impact_level\\":\\"high\\"}]}"}]}}',
            stderr="",
        )
        runner = OpenClawAgentRunner("macro-event-analyst", timeout_seconds=42)
        reply = runner.run(
            AgentTask(
                task_id="task-1",
                agent_role="macro_event_analyst",
                task_kind="event_summary",
                input_id="input-1",
                trace_id="trace-1",
                session_id="macro-event-analyst-session",
                payload={"trace_id": "trace-1"},
            )
        )
        self.assertEqual(reply.status, "completed")
        self.assertEqual(reply.payload, {"events": [{"event_id": "evt-1", "category": "macro", "summary": "Macro shock.", "impact_level": "high"}]})

    @patch("openclaw_trader.modules.agent_gateway.adapters.openclaw._run_command")
    def test_runner_maps_timeout_to_needs_escalation(self, run_mock) -> None:
        run_mock.return_value = _CommandResult(returncode=-1, stdout="", stderr="", timed_out=True)
        runner = OpenClawAgentRunner("pm", timeout_seconds=10)
        reply = runner.run(
            AgentTask(
                task_id="task-1",
                agent_role="pm",
                task_kind="strategy",
                input_id="input-1",
                trace_id="trace-1",
                session_id="pm-session",
                payload={"trace_id": "trace-1"},
            )
        )
        self.assertEqual(reply.status, "needs_escalation")
        self.assertEqual(reply.meta["error_kind"], "agent_timeout")

    def test_runner_uses_rt_workspace_fallback_after_timeout(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            workspace = home / ".openclaw" / "workspace-risk-trader"
            workspace.mkdir(parents=True, exist_ok=True)
            fallback_path = workspace / "execution_submission.json"

            def fake_run(*args, **kwargs):
                fallback_path.write_text(
                    '{"decision_id":"dec-1","strategy_id":"strat-1","generated_at_utc":"2026-03-21T00:00:00Z","trigger_type":"manual","decisions":[{"symbol":"BTC","action":"wait","direction":"long","reason":"fallback","size_pct_of_exposure_budget":0.0,"priority":1,"urgency":"low","valid_for_minutes":10}]}'
                )
                return _CommandResult(returncode=-1, stdout="", stderr="", timed_out=True)

            with patch("openclaw_trader.modules.agent_gateway.adapters.openclaw.Path.home", return_value=home):
                with patch("openclaw_trader.modules.agent_gateway.adapters.openclaw._run_command", side_effect=fake_run):
                    runner = OpenClawAgentRunner("risk-trader", timeout_seconds=10)
                    reply = runner.run(
                        AgentTask(
                            task_id="task-1",
                            agent_role="risk_trader",
                            task_kind="execution",
                            input_id="input-1",
                            trace_id="trace-1",
                            session_id="risk-trader-session",
                            payload={"trace_id": "trace-1"},
                        )
                    )
            self.assertEqual(reply.status, "completed")
            self.assertTrue(reply.meta["fallback_payload_used"])
            self.assertEqual(reply.payload["decision_id"], "dec-1")


if __name__ == "__main__":
    unittest.main()
