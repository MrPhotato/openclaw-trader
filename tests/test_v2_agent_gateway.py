from __future__ import annotations

import unittest
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
from openclaw_trader.modules.policy_risk.service import PolicyRiskService
from openclaw_trader.modules.quant_intelligence.service import QuantIntelligenceService
from openclaw_trader.modules.strategy_intent.models import ExecutionContext
from openclaw_trader.modules.strategy_intent.service import StrategyIntentService
from openclaw_trader.modules.trade_gateway.market_data.service import DataIngestService

from .helpers_v2 import FakeMarketDataProvider, FakeNewsProvider, FakeQuantProvider, build_test_settings


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
        context = ExecutionContext(
            context_id="execctx-1",
            strategy_version="v1",
            coin="BTC",
            product_id="BTC-PERP-INTX",
            target_position_share_pct=15,
            max_position_share_pct=25,
            target_bias="long",
            rationale="test",
        )
        decisions = gateway.request_execution_decisions(trace_id="trace-1", runtime_input=runtime_input, execution_contexts=[context])
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
        strategy_service = StrategyIntentService()
        strategy = strategy_service.ensure_strategy(trace_id="trace-1", reason="dispatch_once", policies=policies)
        execution_contexts = strategy_service.build_execution_contexts(
            strategy=strategy,
            policies=policies,
            market=market,
            forecasts=forecasts,
        )
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
        self.assertEqual(inputs["risk_trader"].payload["strategy"]["strategy_version"], strategy.strategy_version)
        self.assertIn("1h", str(inputs["risk_trader"].payload))
        rt_context = inputs["risk_trader"].payload["execution_contexts"][0]
        self.assertIn("execution_summary", rt_context)
        self.assertNotIn("execution_history", rt_context)
        self.assertNotIn("risk_limits", rt_context)
        self.assertNotIn("position_risk_state", rt_context)
        self.assertNotIn("forecast_snapshot", rt_context)
        self.assertEqual(rt_context["current_position_share_pct"], 4.0)
        self.assertLessEqual(len(inputs["risk_trader"].payload["news_events"]), 5)
        self.assertEqual(inputs["risk_trader"].payload["news_events"][0]["title"], "Macro headline")

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
                "change_summary": "test summary",
                "targets": [
                    {
                        "symbol": "BTC",
                        "state": "active",
                        "direction": "long",
                        "target_exposure_band_pct": [1.0, 2.0],
                        "rt_discretion_band_pct": 1.0,
                        "priority": 1,
                    }
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
                                "size_pct_of_equity": 2.0,
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
                        "size_pct_of_equity": 2.0,
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

    def test_pull_pm_runtime_input_issues_single_runtime_pack_with_lease(self) -> None:
        from .helpers_v2 import build_test_harness

        harness = build_test_harness()
        try:
            pack = harness.container.agent_gateway.pull_pm_runtime_input(
                trigger_type="daily_main",
                params={"cadence_source": "openclaw_cron", "cadence_label": "pm_0100"},
            )
            self.assertEqual(pack.agent_role, "pm")
            self.assertEqual(pack.task_kind, "strategy")
            self.assertEqual(pack.trigger_type, "daily_main")
            self.assertIn("trigger_context", pack.payload)
            lease_asset = harness.container.state_memory.get_asset(pack.input_id)
            self.assertIsNotNone(lease_asset)
            self.assertEqual(lease_asset["asset_type"], "agent_runtime_lease")
            self.assertEqual(lease_asset["payload"]["status"], "issued")
        finally:
            harness.cleanup()

    def test_pull_rt_runtime_input_includes_recent_execution_thoughts(self) -> None:
        from .helpers_v2 import build_test_harness

        harness = build_test_harness()
        try:
            harness.container.state_memory.save_asset(
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
                            "size_pct_of_equity": 3.0,
                            "urgency": "high",
                        }
                    ],
                },
            )
            harness.container.state_memory.save_asset(
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
            self.assertEqual(thoughts[0]["execution_result"]["exchange_order_id"], "order-old-1")
            self.assertEqual(thoughts[0]["execution_result"]["first_fill_price"], "68000")
        finally:
            harness.cleanup()

    def test_submit_strategy_consumes_runtime_pack_and_rejects_reuse(self) -> None:
        from .helpers_v2 import build_test_harness

        harness = build_test_harness()
        try:
            pack = harness.container.agent_gateway.pull_pm_runtime_input(trigger_type="daily_main")
            result = harness.container.agent_gateway.submit_strategy(
                input_id=pack.input_id,
                payload={
                    "portfolio_mode": "normal",
                    "target_gross_exposure_band_pct": [0.0, 5.0],
                    "portfolio_thesis": "agent first thesis",
                    "portfolio_invalidation": "agent first invalidation",
                    "change_summary": "agent first update",
                    "targets": [],
                    "scheduled_rechecks": [],
                },
            )
            self.assertEqual(result["strategy"]["trigger_type"], "daily_main")
            lease_asset = harness.container.state_memory.get_asset(pack.input_id)
            self.assertEqual(lease_asset["payload"]["status"], "consumed")
            with self.assertRaises(RuntimeInputLeaseError) as raised:
                harness.container.agent_gateway.submit_strategy(
                    input_id=pack.input_id,
                    payload={
                        "portfolio_mode": "normal",
                        "target_gross_exposure_band_pct": [0.0, 5.0],
                        "portfolio_thesis": "duplicate",
                        "portfolio_invalidation": "duplicate",
                        "change_summary": "duplicate",
                        "targets": [],
                        "scheduled_rechecks": [],
                    },
                )
            self.assertEqual(raised.exception.reason, "input_already_consumed")
        finally:
            harness.cleanup()

    def test_submit_execution_rejects_wrong_role_input(self) -> None:
        from .helpers_v2 import build_test_harness

        harness = build_test_harness()
        try:
            pack = harness.container.agent_gateway.pull_pm_runtime_input(trigger_type="daily_main")
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
            reminders = harness.container.state_memory.recent_assets(asset_type="direct_reminder", limit=10)
            self.assertEqual(len(reminders), 2)
        finally:
            harness.cleanup()

    def test_submit_retro_consumes_chief_runtime_pack(self) -> None:
        from .helpers_v2 import build_test_harness

        harness = build_test_harness()
        try:
            pack = harness.container.agent_gateway.pull_chief_retro_pack(trigger_type="daily_retro")
            result = harness.container.agent_gateway.submit_retro(input_id=pack.input_id)
            self.assertTrue(result["owner_summary"])
            self.assertEqual(len(result["transcript"]), 8)
            lease_asset = harness.container.state_memory.get_asset(pack.input_id)
            self.assertEqual(lease_asset["payload"]["status"], "consumed")
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
                        "change_summary": "repaired summary",
                        "targets": [],
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

    def test_run_chief_retro_retries_empty_owner_summary_once(self) -> None:
        class FlakyChiefRunner:
            def __init__(self) -> None:
                self.calls: list[AgentTask] = []

            def run(self, task: AgentTask) -> AgentReply:
                self.calls.append(task)
                if task.task_kind == "retro_turn":
                    return AgentReply(
                        task_id=task.task_id,
                        agent_role=task.agent_role,
                        status="completed",
                        payload={"speaker_role": "crypto_chief", "statement": "Chief round close."},
                        meta={"stdout": '{"speaker_role":"crypto_chief","statement":"Chief round close."}'},
                    )
                retro_calls = [item for item in self.calls if item.task_kind == "retro"]
                learning_results = _write_learning_targets(list(task.payload.get("learning_targets") or []))
                if len(retro_calls) == 1:
                    return AgentReply(
                        task_id=task.task_id,
                        agent_role=task.agent_role,
                        status="completed",
                        payload={
                            "owner_summary": "   ",
                            "reset_command": "/new",
                            "learning_completed": True,
                            "learning_results": learning_results,
                        },
                        meta={
                            "stdout": '{"owner_summary":"   ","reset_command":"/new","learning_completed":true,"learning_results":[{"agent_role":"pm","learning_updated":true,"learning_path":"...","learning_summary":"pm learned one lesson from retro."}]}'
                        },
                    )
                return AgentReply(
                    task_id=task.task_id,
                    agent_role=task.agent_role,
                    status="completed",
                    payload={
                        "owner_summary": "Retro summary ready.",
                        "reset_command": "/new",
                        "learning_completed": True,
                        "learning_results": learning_results,
                    },
                    meta={
                        "stdout": '{"owner_summary":"Retro summary ready.","reset_command":"/new","learning_completed":true,"learning_results":[]}'
                    },
                )

        runner = FlakyChiefRunner()
        with TemporaryDirectory() as tempdir:
            learning_root = Path(tempdir)
            gateway = AgentGatewayService(
                pm_runner=DeterministicAgentRunner(),
                risk_runner=DeterministicAgentRunner(),
                macro_runner=DeterministicAgentRunner(),
                chief_runner=runner,
                session_controller=DeterministicSessionController(),
                learning_path_by_role={
                    "pm": str(learning_root / "pm.md"),
                    "risk_trader": str(learning_root / "rt.md"),
                    "macro_event_analyst": str(learning_root / "mea.md"),
                    "crypto_chief": "/tmp/chief-learning.md",
                },
            )
            payload = gateway.run_chief_retro(
                trace_id="trace-1",
                runtime_inputs={
                    "pm": AgentRuntimeInput(input_id="input-pm", agent_role="pm", task_kind="strategy", payload={"trace_id": "trace-1"}),
                    "risk_trader": AgentRuntimeInput(input_id="input-rt", agent_role="risk_trader", task_kind="execution", payload={"trace_id": "trace-1"}),
                    "macro_event_analyst": AgentRuntimeInput(input_id="input-mea", agent_role="macro_event_analyst", task_kind="event_summary", payload={"trace_id": "trace-1"}),
                    "crypto_chief": AgentRuntimeInput(
                        input_id="input-chief",
                        agent_role="crypto_chief",
                        task_kind="retro",
                        payload={"trace_id": "trace-1"},
                    ),
                },
            )
            self.assertEqual(payload["owner_summary"], "Retro summary ready.")
            retro_calls = [item for item in runner.calls if item.task_kind == "retro"]
            self.assertEqual(len(retro_calls), 2)
            expected_session_id = gateway.session_id_for_role("crypto_chief")
            self.assertEqual(retro_calls[0].session_id, expected_session_id)
            self.assertEqual(retro_calls[1].session_id, expected_session_id)
            self.assertEqual(retro_calls[1].payload["mode"], "retro_summary_repair")

    def test_run_chief_retro_drives_two_round_meeting_and_owner_summary(self) -> None:
        class RecordingRunner:
            def __init__(self, agent_role: str) -> None:
                self.agent_role = agent_role
                self.calls: list[AgentTask] = []

            def run(self, task: AgentTask) -> AgentReply:
                self.calls.append(task)
                if task.task_kind == "retro_turn":
                    return AgentReply(
                        task_id=task.task_id,
                        agent_role=task.agent_role,
                        status="completed",
                        payload={
                            "speaker_role": task.agent_role,
                            "statement": f"{task.agent_role}-round-{task.payload['round_index']}",
                        },
                    )
                if task.task_kind == "retro":
                    learning_results = _write_learning_targets(list(task.payload.get("learning_targets") or []))
                    return AgentReply(
                        task_id=task.task_id,
                        agent_role=task.agent_role,
                        status="completed",
                        payload={
                            "owner_summary": "Retro owner summary ready.",
                            "reset_command": "/new",
                            "learning_completed": True,
                            "learning_results": learning_results,
                        },
                    )
                return AgentReply(
                    task_id=task.task_id,
                    agent_role=task.agent_role,
                    status="completed",
                    payload={"decision": "unused"},
                )

        with TemporaryDirectory() as tempdir:
            learning_root = Path(tempdir)
            pm_runner = RecordingRunner("pm")
            rt_runner = RecordingRunner("risk_trader")
            mea_runner = RecordingRunner("macro_event_analyst")
            chief_runner = RecordingRunner("crypto_chief")
            gateway = AgentGatewayService(
                pm_runner=pm_runner,
                risk_runner=rt_runner,
                macro_runner=mea_runner,
                chief_runner=chief_runner,
                session_controller=DeterministicSessionController(),
                learning_path_by_role={
                    "pm": str(learning_root / "pm.md"),
                    "risk_trader": str(learning_root / "rt.md"),
                    "macro_event_analyst": str(learning_root / "mea.md"),
                    "crypto_chief": str(learning_root / "chief.md"),
                },
            )
            payload = gateway.run_chief_retro(
                trace_id="trace-meeting",
                runtime_inputs={
                    "pm": AgentRuntimeInput(
                        input_id="input-pm",
                        agent_role="pm",
                        task_kind="strategy",
                        payload={
                            "trace_id": "trace-meeting",
                            "market": {
                                "market": {"BTC": {"mark_price": "70000", "funding_rate": "0.0001", "open_interest": "123", "day_notional_volume": "456", "trading_status": "STANDARD"}},
                                "accounts": {"BTC": {"current_side": None, "current_notional_usd": None}},
                                "market_context": {"BTC": {"shape_summary": "range", "breakout_retest_state": {"state": "range"}, "volatility_state": {"state": "normal"}}},
                                "execution_history": {"BTC": {"summary": {"recent_order_count": 1}}},
                                "portfolio": {"total_equity_usd": "1000", "available_equity_usd": "900", "total_exposure_usd": "0", "positions": []},
                            },
                            "risk_limits": {"BTC": {"trade_availability": {"tradable": True, "reasons": []}, "risk_limits": {"max_leverage": 5.0}}},
                            "forecasts": {"BTC": {"1h": {"side": "flat", "confidence": 0.0}}},
                            "previous_strategy": {
                                "strategy_id": "strategy-1",
                                "revision_number": 3,
                                "portfolio_mode": "defensive",
                                "portfolio_thesis": "Stay defensive.",
                                "portfolio_invalidation": "Break higher.",
                                "change_summary": "No change.",
                                "targets": [{"symbol": "BTC", "state": "active", "direction": "long", "target_exposure_band_pct": [0, 10], "rt_discretion_band_pct": 2.0, "priority": 1}],
                            },
                            "news_events": [{"news_id": "news-1", "title": "Fed", "summary": "Policy unchanged", "severity": "medium"}],
                            "macro_memory": [{"memory_day_utc": "2026-03-21", "summary": "Quiet macro day", "event_ids": ["news-1"]}],
                        },
                    ),
                    "risk_trader": AgentRuntimeInput(
                        input_id="input-rt",
                        agent_role="risk_trader",
                        task_kind="execution",
                        payload={
                            "trace_id": "trace-meeting",
                            "strategy": {"strategy_id": "strategy-1", "portfolio_mode": "defensive", "targets": []},
                            "execution_contexts": [{"coin": "BTC", "product_id": "BTC-PERP-INTX", "target": {"state": "active", "direction": "long", "target_exposure_band_pct": [0, 10], "rt_discretion_band_pct": 2.0}, "current_position_share_pct": 0.0, "market_snapshot": {"mark_price": "70000", "trading_status": "STANDARD"}, "execution_summary": {"recent_order_count": 1}}],
                        },
                    ),
                    "macro_event_analyst": AgentRuntimeInput(
                        input_id="input-mea",
                        agent_role="macro_event_analyst",
                        task_kind="event_summary",
                        payload={
                            "trace_id": "trace-meeting",
                            "market": {
                                "market": {"BTC": {"mark_price": "70000", "funding_rate": "0.0001", "open_interest": "123", "day_notional_volume": "456", "trading_status": "STANDARD"}},
                                "accounts": {"BTC": {"current_side": None, "current_notional_usd": None}},
                                "market_context": {"BTC": {"shape_summary": "range", "breakout_retest_state": {"state": "range"}, "volatility_state": {"state": "normal"}}},
                                "execution_history": {"BTC": {"summary": {"recent_order_count": 1}}},
                                "portfolio": {"total_equity_usd": "1000", "available_equity_usd": "900", "total_exposure_usd": "0", "positions": []},
                            },
                            "news_events": [{"news_id": "news-1", "title": "Fed", "summary": "Policy unchanged", "severity": "medium"}],
                            "macro_memory": [{"memory_day_utc": "2026-03-21", "summary": "Quiet macro day", "event_ids": ["news-1"]}],
                        },
                    ),
                    "crypto_chief": AgentRuntimeInput(input_id="input-chief", agent_role="crypto_chief", task_kind="retro", payload={"trace_id": "trace-meeting"}),
                },
            )

            self.assertEqual(payload["round_count"], 2)
            self.assertEqual(len(payload["transcript"]), 8)
            self.assertEqual(
                [item["speaker_role"] for item in payload["transcript"][:4]],
                ["pm", "risk_trader", "macro_event_analyst", "crypto_chief"],
            )
            self.assertEqual(payload["owner_summary"], "Retro owner summary ready.")
            self.assertEqual(len([item for item in pm_runner.calls if item.task_kind == "retro_turn"]), 2)
            self.assertEqual(len([item for item in rt_runner.calls if item.task_kind == "retro_turn"]), 2)
            self.assertEqual(len([item for item in mea_runner.calls if item.task_kind == "retro_turn"]), 2)
            self.assertEqual(len([item for item in chief_runner.calls if item.task_kind == "retro_turn"]), 2)
            self.assertEqual(len([item for item in chief_runner.calls if item.task_kind == "retro"]), 1)
            self.assertEqual(len([item for item in pm_runner.calls if item.task_kind == "retro_learning"]), 0)
            self.assertEqual(len([item for item in rt_runner.calls if item.task_kind == "retro_learning"]), 0)
            self.assertEqual(len([item for item in mea_runner.calls if item.task_kind == "retro_learning"]), 0)
            retro_summary_call = [item for item in chief_runner.calls if item.task_kind == "retro"][0]
            self.assertIn("session_key", retro_summary_call.payload["learning_targets"][0])
            self.assertEqual(
                retro_summary_call.payload["learning_targets"][0]["session_key"],
                "agent:pm:main",
            )
            self.assertIn("Use the exact session_key", retro_summary_call.payload["instruction"])
            self.assertEqual(len(pm_runner.calls[0].payload["transcript"]), 0)
            self.assertEqual(len(rt_runner.calls[0].payload["transcript"]), 1)
            self.assertEqual(len(chief_runner.calls[0].payload["transcript"]), 3)
            self.assertEqual(len(pm_runner.calls[1].payload["transcript"]), 3)
            self.assertEqual(len(rt_runner.calls[1].payload["transcript"]), 3)
            self.assertEqual(len(mea_runner.calls[1].payload["transcript"]), 3)
            self.assertEqual(len(chief_runner.calls[1].payload["transcript"]), 3)
            self.assertEqual(pm_runner.calls[0].payload["transcript_mode"], "initial_full_pack")
            self.assertEqual(pm_runner.calls[1].payload["transcript_mode"], "delta_since_last_turn")
            self.assertIn("runtime_input", pm_runner.calls[0].payload)
            self.assertIn("market_summary", pm_runner.calls[0].payload["runtime_input"])
            self.assertIn("strategy_summary", pm_runner.calls[0].payload["runtime_input"])
            self.assertIn("news_summary", pm_runner.calls[0].payload["runtime_input"])
            self.assertNotIn("market", pm_runner.calls[0].payload["runtime_input"])
            self.assertNotIn("runtime_input", pm_runner.calls[1].payload)
            self.assertNotIn("runtime_input", chief_runner.calls[-1].payload)

    def test_run_chief_retro_resets_same_session_once_on_agent_timeout(self) -> None:
        class TimeoutThenSuccessChiefRunner:
            def __init__(self) -> None:
                self.calls: list[AgentTask] = []

            def run(self, task: AgentTask) -> AgentReply:
                self.calls.append(task)
                if task.task_kind == "retro_turn":
                    return AgentReply(
                        task_id=task.task_id,
                        agent_role=task.agent_role,
                        status="completed",
                        payload={"speaker_role": "crypto_chief", "statement": "Chief round close."},
                    )
                retro_calls = [item for item in self.calls if item.task_kind == "retro"]
                if len(retro_calls) == 1:
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
                learning_results = _write_learning_targets(list(task.payload.get("learning_targets") or []))
                return AgentReply(
                    task_id=task.task_id,
                    agent_role=task.agent_role,
                    status="completed",
                    payload={
                        "owner_summary": "Retro summary ready.",
                        "reset_command": "/new",
                        "learning_completed": True,
                        "learning_results": learning_results,
                    },
                    meta={
                        "stdout": '{"owner_summary":"Retro summary ready.","reset_command":"/new","learning_completed":true,"learning_results":[]}'
                    },
                )

        class RecordingSessionController:
            def __init__(self) -> None:
                self.resets: list[tuple[str, str, str]] = []

            def reset(self, *, agent_role: str, session_id: str, reset_command: str = "/new") -> dict[str, object]:
                self.resets.append((agent_role, session_id, reset_command))
                return {"success": True, "agent_role": agent_role, "session_id": session_id, "reset_command": reset_command}

        runner = TimeoutThenSuccessChiefRunner()
        session_controller = RecordingSessionController()
        gateway = AgentGatewayService(
            pm_runner=DeterministicAgentRunner(),
            risk_runner=DeterministicAgentRunner(),
            macro_runner=DeterministicAgentRunner(),
            chief_runner=runner,
            session_controller=session_controller,
            learning_path_by_role={
                "pm": "/tmp/pm-learning.md",
                "risk_trader": "/tmp/rt-learning.md",
                "macro_event_analyst": "/tmp/mea-learning.md",
                "crypto_chief": "/tmp/chief-learning.md",
            },
        )
        payload = gateway.run_chief_retro(
            trace_id="trace-1",
            runtime_inputs={
                "pm": AgentRuntimeInput(input_id="input-pm", agent_role="pm", task_kind="strategy", payload={"trace_id": "trace-1"}),
                "risk_trader": AgentRuntimeInput(input_id="input-rt", agent_role="risk_trader", task_kind="execution", payload={"trace_id": "trace-1"}),
                "macro_event_analyst": AgentRuntimeInput(input_id="input-mea", agent_role="macro_event_analyst", task_kind="event_summary", payload={"trace_id": "trace-1"}),
                "crypto_chief": AgentRuntimeInput(
                    input_id="input-chief",
                    agent_role="crypto_chief",
                    task_kind="retro",
                    payload={"trace_id": "trace-1"},
                ),
            },
        )
        self.assertEqual(payload["owner_summary"], "Retro summary ready.")
        self.assertEqual(len([item for item in runner.calls if item.task_kind == "retro"]), 2)
        self.assertEqual(len(session_controller.resets), 1)
        expected_session_id = gateway.session_id_for_role("crypto_chief")
        self.assertEqual(session_controller.resets[0][0], "crypto_chief")
        self.assertEqual(session_controller.resets[0][1], expected_session_id)

    def test_run_chief_retro_resets_pm_session_once_on_retro_turn_timeout(self) -> None:
        class FlakyPmRunner:
            def __init__(self) -> None:
                self.calls: list[AgentTask] = []

            def run(self, task: AgentTask) -> AgentReply:
                self.calls.append(task)
                if task.task_kind == "retro_turn" and len([item for item in self.calls if item.task_kind == "retro_turn"]) == 1:
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
                    payload={"speaker_role": task.agent_role, "statement": f"{task.agent_role}-ok"},
                )

        class SteadyRetroRunner:
            def __init__(self, agent_role: str) -> None:
                self.agent_role = agent_role
                self.calls: list[AgentTask] = []

            def run(self, task: AgentTask) -> AgentReply:
                self.calls.append(task)
                if task.task_kind == "retro_turn":
                    return AgentReply(
                        task_id=task.task_id,
                        agent_role=task.agent_role,
                        status="completed",
                        payload={"speaker_role": task.agent_role, "statement": f"{task.agent_role}-ok"},
                    )
                if task.task_kind == "retro":
                    learning_results = _write_learning_targets(list(task.payload.get("learning_targets") or []))
                    return AgentReply(
                        task_id=task.task_id,
                        agent_role=task.agent_role,
                        status="completed",
                        payload={
                            "owner_summary": "Retro owner summary ready.",
                            "reset_command": "/new",
                            "learning_completed": True,
                            "learning_results": learning_results,
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
                learning_path_by_role={
                    "pm": str(learning_root / "pm.md"),
                    "risk_trader": str(learning_root / "rt.md"),
                    "macro_event_analyst": str(learning_root / "mea.md"),
                    "crypto_chief": str(learning_root / "chief.md"),
                },
            )
            payload = gateway.run_chief_retro(
                trace_id="trace-retry",
                runtime_inputs={
                    "pm": AgentRuntimeInput(input_id="input-pm", agent_role="pm", task_kind="strategy", payload={"trace_id": "trace-retry"}),
                    "risk_trader": AgentRuntimeInput(input_id="input-rt", agent_role="risk_trader", task_kind="execution", payload={"trace_id": "trace-retry"}),
                    "macro_event_analyst": AgentRuntimeInput(input_id="input-mea", agent_role="macro_event_analyst", task_kind="event_summary", payload={"trace_id": "trace-retry"}),
                    "crypto_chief": AgentRuntimeInput(input_id="input-chief", agent_role="crypto_chief", task_kind="retro", payload={"trace_id": "trace-retry"}),
                },
            )
            self.assertEqual(payload["round_count"], 2)
            self.assertEqual(len([item for item in pm_runner.calls if item.task_kind == "retro_turn"]), 3)
            self.assertEqual(len(session_controller.resets), 1)
            self.assertEqual(session_controller.resets[0][0], "pm")
            self.assertEqual(session_controller.resets[0][1], gateway.session_id_for_role("pm"))

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
                    '{"decision_id":"dec-1","strategy_id":"strat-1","generated_at_utc":"2026-03-21T00:00:00Z","trigger_type":"manual","decisions":[{"symbol":"BTC","action":"wait","direction":"long","reason":"fallback","size_pct_of_equity":0.0,"priority":1,"urgency":"low","valid_for_minutes":10}]}'
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
