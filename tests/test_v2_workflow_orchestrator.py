from __future__ import annotations

import unittest
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from openclaw_trader.modules.trade_gateway.market_data import (
    BreakoutRetestState,
    CompressedPriceSeries,
    DataIngestService,
    KeyLevel,
    MarketContextNormalized,
    MarketSnapshotNormalized,
    PortfolioSnapshot,
    PriceSeriesPoint,
    VolatilityState,
)
from openclaw_trader.modules.workflow_orchestrator.models import ManualTriggerCommand
from openclaw_trader.modules.workflow_orchestrator.pm_recheck import PMRecheckConfig, PMRecheckMonitor
from openclaw_trader.modules.workflow_orchestrator.retro_prep import RetroPrepConfig, RetroPrepMonitor
from openclaw_trader.modules.workflow_orchestrator.risk_brake import RiskBrakeConfig, RiskBrakeMonitor
from openclaw_trader.modules.workflow_orchestrator.rt_trigger import OpenClawCronRunner, RTTriggerConfig, RTTriggerMonitor

from .helpers_v2 import FakeMarketDataProvider, build_test_harness
from .test_v2_agent_gateway import _seed_pending_retro_case, _valid_strategy_targets


class FakeCronRunner:
    def __init__(self) -> None:
        self.runs: list[str] = []
        self.running = False

    def is_running(self, *, job_id: str) -> bool:
        return self.running

    def run_now(self, *, job_id: str):
        from openclaw_trader.modules.workflow_orchestrator.rt_trigger import CronRunResult

        self.runs.append(job_id)
        return CronRunResult(ok=True, stdout='{"ok":true}', stderr="", returncode=0)

    def run_now_detached(self, *, job_id: str):
        from openclaw_trader.modules.workflow_orchestrator.rt_trigger import CronSpawnResult

        self.runs.append(job_id)
        return CronSpawnResult(ok=True, pid=43210)


class FakeRTTriggerMonitor:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class MutableMarketDataProvider(FakeMarketDataProvider):
    def __init__(self) -> None:
        self.breakout_by_coin: dict[str, str] = {}
        self.volatility_by_coin: dict[str, str] = {}
        self.mark_by_coin: dict[str, str] = {}
        self.unrealized_pnl_usd = "0"
        self.portfolio_total_equity_usd = "1000"
        self.portfolio_available_equity_usd = "800"
        self.flat = False

    def collect_market(self, coins: list[str]) -> dict[str, MarketSnapshotNormalized]:
        payload = super().collect_market(coins)
        for coin, price in self.mark_by_coin.items():
            if coin in payload:
                payload[coin] = payload[coin].model_copy(update={"mark_price": price})
        return payload

    def collect_portfolio(self) -> PortfolioSnapshot:
        if self.flat:
            return PortfolioSnapshot(total_equity_usd="1000", available_equity_usd="1000", total_exposure_usd="0")
        portfolio = super().collect_portfolio()
        return portfolio.model_copy(
            update={
                "total_equity_usd": self.portfolio_total_equity_usd,
                "available_equity_usd": self.portfolio_available_equity_usd,
                "unrealized_pnl_usd": self.unrealized_pnl_usd,
                "positions": [
                    position.model_copy(update={"unrealized_pnl_usd": self.unrealized_pnl_usd})
                    for position in portfolio.positions
                ],
            }
        )

    def collect_market_context(self, coins: list[str]) -> dict[str, MarketContextNormalized]:
        contexts: dict[str, MarketContextNormalized] = {}
        for coin in coins:
            contexts[coin] = MarketContextNormalized(
                coin=coin,
                product_id=f"{coin}-PERP-INTX",
                compressed_price_series={
                    "15m": CompressedPriceSeries(
                        window="15m",
                        granularity="FIFTEEN_MINUTE",
                        points=[
                            PriceSeriesPoint(timestamp=1, close="99"),
                            PriceSeriesPoint(timestamp=2, close=self.mark_by_coin.get(coin, "100")),
                        ],
                        change_pct=1.0,
                    )
                },
                key_levels=[
                    KeyLevel(label="1h_high", price="105", source="1h"),
                    KeyLevel(label="1h_low", price="95", source="1h"),
                    KeyLevel(label="4h_high", price="110", source="4h"),
                    KeyLevel(label="4h_low", price="90", source="4h"),
                ],
                breakout_retest_state=BreakoutRetestState(
                    state=self.breakout_by_coin.get(coin, "range"),
                    reference_level="1h_range",
                    reference_price=self.mark_by_coin.get(coin, "100"),
                ),
                volatility_state=VolatilityState(state=self.volatility_by_coin.get(coin, "normal")),
                shape_summary="uptrend|range|normal|above_mean",
            )
        return contexts


def _build_monitor(harness, *, provider: MutableMarketDataProvider | None = None, config: RTTriggerConfig | None = None):
    runner = FakeCronRunner()
    market_data = DataIngestService(provider or MutableMarketDataProvider())
    monitor = RTTriggerMonitor(
        memory_assets=harness.container.memory_assets,
        market_data=market_data,
        event_bus=harness.event_bus,
        config=config
        or RTTriggerConfig(
            enabled=True,
            rt_job_id="rt-job",
            global_cooldown_seconds=300,
            key_cooldown_seconds=900,
            max_runs_per_hour=4,
            execution_followup_delay_seconds=180,
            max_leverage=5.0,
        ),
        cron_runner=runner,
    )
    return monitor, runner


def _seed_trigger_state(harness, payload: dict) -> None:
    harness.container.memory_assets.save_asset(
        asset_type="rt_trigger_state",
        asset_id="rt_trigger_state",
        actor_role="system",
        payload=payload,
    )


def _strategy_key(strategy_asset: dict) -> str:
    payload = strategy_asset.get("payload") or strategy_asset
    return f"{payload['strategy_id']}:{payload['revision_number']}"


def _seed_strategy(harness, *, gross_band: list[float] | None = None, targets: list[dict] | None = None) -> dict:
    merged_targets = {str(item["symbol"]).upper(): dict(item) for item in (targets or [])}
    if not merged_targets:
        merged_targets = {item["symbol"]: item for item in _valid_strategy_targets()}
    else:
        for item in _valid_strategy_targets():
            merged_targets.setdefault(str(item["symbol"]).upper(), item)
    return harness.container.memory_assets.materialize_strategy_asset(
        trace_id="trace-seed-strategy",
        authored_payload={
            "portfolio_mode": "normal",
            "target_gross_exposure_band_pct": gross_band or [0.0, 20.0],
            "portfolio_thesis": "Seed strategy.",
            "portfolio_invalidation": "Seed invalidation.",
            "flip_triggers": "flip when multi-horizon structure and macro regime both reverse",
            "change_summary": "Seeded strategy.",
            "targets": [
                merged_targets["BTC"],
                merged_targets["ETH"],
            ],
            "scheduled_rechecks": [],
        },
        trigger_type="scheduled",
    )


def _seed_risk_brake_state(harness, payload: dict) -> None:
    harness.container.memory_assets.save_asset(
        asset_type="risk_brake_state",
        asset_id="risk_brake_state",
        actor_role="system",
        payload=payload,
    )


def _build_risk_brake_monitor(harness, *, provider: MutableMarketDataProvider | None = None):
    runner = FakeCronRunner()
    monitor = RiskBrakeMonitor(
        memory_assets=harness.container.memory_assets,
        market_data=DataIngestService(provider or MutableMarketDataProvider()),
        policy_risk=harness.container.policy_risk,
        trade_execution=harness.container.trade_execution,
        event_bus=harness.event_bus,
        config=RiskBrakeConfig(
            enabled=True,
            scan_interval_seconds=30,
            rt_job_id="rt-job",
            pm_job_id="pm-job",
            cron_subprocess_timeout_seconds=15,
        ),
        cron_runner=runner,
    )
    return monitor, runner


def _build_pm_recheck_monitor(harness, *, config: PMRecheckConfig | None = None):
    runner = FakeCronRunner()
    monitor = PMRecheckMonitor(
        memory_assets=harness.container.memory_assets,
        event_bus=harness.event_bus,
        config=config
        or PMRecheckConfig(
            enabled=True,
            pm_job_id="pm-job",
            scan_interval_seconds=30,
            cron_subprocess_timeout_seconds=15,
        ),
        cron_runner=runner,
    )
    return monitor, runner


def _build_retro_prep_monitor(harness, *, config: RetroPrepConfig | None = None):
    runner = FakeCronRunner()
    return RetroPrepMonitor(
        memory_assets=harness.container.memory_assets,
        agent_gateway=harness.container.agent_gateway,
        event_bus=harness.event_bus,
        config=config
        or RetroPrepConfig(
            enabled=True,
            scan_interval_seconds=30,
            prep_hour_utc=22,
            prep_minute_utc=40,
            chief_job_id="chief-job",
        ),
        cron_runner=runner,
    ), runner


class WorkflowOrchestratorTests(unittest.TestCase):
    def test_legacy_market_commands_are_rejected(self) -> None:
        harness = build_test_harness()
        try:
            for index, command_type in enumerate(("dispatch_once", "run_pm", "run_rt", "run_mea", "refresh_strategy", "rerun_trade_review"), start=1):
                receipt = harness.container.workflow_orchestrator.submit_command(
                    ManualTriggerCommand(
                        command_id=f"cmd-legacy-{index}",
                        command_type=command_type,
                        initiator="risk_trader",
                    )
                )
                self.assertFalse(receipt.accepted)
                self.assertEqual(receipt.reason, "legacy_market_workflow_disabled_use_agent_cron")
        finally:
            harness.cleanup()

    def test_path_4_run_retro_prep_dispatches_chief_cron_without_running_sync_retro(self) -> None:
        harness = build_test_harness(news_severity="high")
        try:
            harness.container.memory_assets.materialize_strategy_asset(
                trace_id="trace-seed-strategy",
                authored_payload={
                    "portfolio_mode": "defensive",
                    "target_gross_exposure_band_pct": [5.0, 15.0],
                    "portfolio_thesis": "Seed strategy for retro.",
                    "portfolio_invalidation": "Seed invalidation.",
                    "flip_triggers": "flip when multi-horizon structure and macro regime both reverse",
                    "change_summary": "Seeded before retro.",
                    "targets": _valid_strategy_targets(),
                    "scheduled_rechecks": [],
                },
                trigger_type="manual",
            )
            monitor, runner = _build_retro_prep_monitor(harness)
            orchestrator = type(harness.container.workflow_orchestrator)(
                memory_assets=harness.container.memory_assets,
                event_bus=harness.event_bus,
                executor=harness.container.workflow_orchestrator.executor,
                retro_prep_monitor=monitor,  # type: ignore[arg-type]
            )
            try:
                receipt = orchestrator.submit_command(
                    ManualTriggerCommand(command_id="cmd-retro-prep", command_type="run_retro_prep", initiator="test")
                )
                self.assertTrue(receipt.accepted)
                workflow = orchestrator.wait_for_workflow(receipt.trace_id)
                self.assertEqual(workflow.state, "completed")
                result = harness.container.memory_assets.get_workflow(receipt.trace_id)
                self.assertIsNotNone(result)
                prep_state = harness.container.memory_assets.get_asset("retro_prep_state")
                self.assertIsNotNone(prep_state)
                self.assertEqual(prep_state["payload"]["last_dispatch_status"], "dispatched")
                self.assertEqual(runner.runs, ["chief-job"])
                retro_case = harness.container.memory_assets.latest_retro_case(case_day_utc=datetime.now(UTC).date().isoformat())
                self.assertIsNotNone(retro_case)
                self.assertEqual(len(harness.container.memory_assets.get_retro_briefs(case_id=retro_case["case_id"])), 3)
                self.assertEqual(len(harness.fake_session_controller.resets), 0)
            finally:
                orchestrator.close()
        finally:
            harness.cleanup()

    def test_path_5_reset_agent_sessions_runs_under_workflow_orchestrator(self) -> None:
        harness = build_test_harness()
        try:
            receipt = harness.container.workflow_orchestrator.submit_command(
                ManualTriggerCommand(command_id="cmd-reset", command_type="reset_agent_sessions", initiator="test")
            )
            self.assertTrue(receipt.accepted)
            workflow = harness.wait_for_workflow(receipt.trace_id)
            self.assertEqual(workflow.state, "completed")
            self.assertEqual(len(harness.fake_session_controller.resets), 4)
            agent_sessions = harness.container.memory_assets.list_agent_sessions()
            self.assertTrue(
                all(session["last_reset_command"] == "/new" for session in agent_sessions if session["agent_role"] != "system")
            )
        finally:
            harness.cleanup()

    def test_path_5_reset_agent_sessions_persists_effective_session_id(self) -> None:
        harness = build_test_harness()
        try:
            original_reset = harness.fake_session_controller.reset

            def reset_with_new_session(*, agent_role: str, session_id: str, reset_command: str = "/new"):
                payload = original_reset(agent_role=agent_role, session_id=session_id, reset_command=reset_command)
                if agent_role == "pm":
                    payload["effective_session_id"] = "pm-new-session"
                return payload

            harness.fake_session_controller.reset = reset_with_new_session
            receipt = harness.container.workflow_orchestrator.submit_command(
                ManualTriggerCommand(command_id="cmd-reset-effective", command_type="reset_agent_sessions", initiator="test")
            )
            workflow = harness.wait_for_workflow(receipt.trace_id)
            self.assertEqual(workflow.state, "completed")
            pm_session = next(
                session
                for session in harness.container.memory_assets.list_agent_sessions()
                if session["agent_role"] == "pm"
            )
            self.assertEqual(pm_session["session_id"], "pm-new-session")
        finally:
            harness.cleanup()

    def test_legacy_market_commands_never_create_workflows(self) -> None:
        harness = build_test_harness()
        try:
            receipt = harness.container.workflow_orchestrator.submit_command(
                ManualTriggerCommand(command_id="cmd-invalid-pm", command_type="run_pm", initiator="test")
            )
            self.assertFalse(receipt.accepted)
            self.assertEqual(receipt.reason, "legacy_market_workflow_disabled_use_agent_cron")
            self.assertIsNone(harness.container.memory_assets.get_workflow_by_command("cmd-invalid-pm"))
        finally:
            harness.cleanup()

    def test_rt_trigger_monitor_is_disabled_by_default(self) -> None:
        harness = build_test_harness()
        try:
            self.assertIsNone(harness.container.workflow_orchestrator._rt_trigger_monitor)
        finally:
            harness.cleanup()

    def test_rt_trigger_monitor_is_started_and_stopped_when_supplied(self) -> None:
        harness = build_test_harness()
        try:
            fake_monitor = FakeRTTriggerMonitor()
            orchestrator = type(harness.container.workflow_orchestrator)(
                memory_assets=harness.container.memory_assets,
                event_bus=harness.event_bus,
                executor=harness.container.workflow_orchestrator.executor,
                rt_trigger_monitor=fake_monitor,  # type: ignore[arg-type]
            )
            self.assertTrue(fake_monitor.started)
            orchestrator.close()
            self.assertTrue(fake_monitor.stopped)
        finally:
            harness.cleanup()

    def test_pm_recheck_monitor_dispatches_due_recheck_via_pm_cron(self) -> None:
        harness = build_test_harness()
        try:
            now = datetime(2026, 4, 10, 3, 0, tzinfo=UTC)
            _seed_strategy(
                harness,
                targets=[],
            )
            latest = harness.container.memory_assets.get_latest_strategy()
            payload = dict((latest or {}).get("payload") or {})
            payload["scheduled_rechecks"] = [
                {
                    "recheck_at_utc": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                    "scope": "portfolio",
                    "reason": "Asia session recheck",
                }
            ]
            harness.container.memory_assets.save_strategy(payload["strategy_id"], "trace-seed-strategy", payload)
            harness.container.memory_assets.save_asset(
                asset_type="strategy",
                asset_id="strategy-current",
                payload=payload,
                trace_id="trace-seed-strategy",
                actor_role="pm",
            )
            monitor, runner = _build_pm_recheck_monitor(harness)
            result = monitor.scan_once(now=now)
            self.assertTrue(result["triggered"])
            self.assertEqual(result["reason"], "scheduled_recheck")
            self.assertTrue(result["dispatched"])
            self.assertEqual(runner.runs, ["pm-job"])
            event_asset = harness.container.memory_assets.latest_asset(asset_type="pm_trigger_event", actor_role="system")
            self.assertIsNotNone(event_asset)
            self.assertEqual(event_asset["payload"]["trigger_type"], "scheduled_recheck")
        finally:
            harness.cleanup()

    def test_pm_recheck_monitor_skips_already_dispatched_due_recheck(self) -> None:
        harness = build_test_harness()
        try:
            now = datetime(2026, 4, 10, 3, 0, tzinfo=UTC)
            _seed_strategy(harness, targets=[])
            latest = harness.container.memory_assets.get_latest_strategy()
            payload = dict((latest or {}).get("payload") or {})
            recheck = {
                "recheck_at_utc": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                "scope": "portfolio",
                "reason": "Asia session recheck",
            }
            payload["scheduled_rechecks"] = [recheck]
            harness.container.memory_assets.save_strategy(payload["strategy_id"], "trace-seed-strategy", payload)
            harness.container.memory_assets.save_asset(
                asset_type="strategy",
                asset_id="strategy-current",
                payload=payload,
                trace_id="trace-seed-strategy",
                actor_role="pm",
            )
            recheck_key = f"{payload['strategy_id']}|{recheck['recheck_at_utc']}|portfolio|{recheck['reason']}"
            harness.container.memory_assets.save_asset(
                asset_type="pm_recheck_state",
                asset_id="pm_recheck_state",
                actor_role="system",
                payload={"completed_recheck_keys": [recheck_key]},
            )
            monitor, runner = _build_pm_recheck_monitor(harness)
            result = monitor.scan_once(now=now)
            self.assertFalse(result["triggered"])
            self.assertEqual(result["skipped_reason"], "already_dispatched")
            self.assertEqual(runner.runs, [])
        finally:
            harness.cleanup()

    def test_retro_prep_monitor_prepares_case_and_briefs_before_chief_pull(self) -> None:
        harness = build_test_harness()
        try:
            monitor, runner = _build_retro_prep_monitor(harness)
            now = datetime(2026, 4, 12, 22, 45, tzinfo=UTC)
            result = monitor.scan_once(now=now)
            self.assertTrue(result["triggered"])
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["retro_brief_count"], 3)
            self.assertTrue(result["chief_dispatched"])
            self.assertEqual(result["chief_dispatch_status"], "dispatched")
            self.assertEqual(runner.runs, ["chief-job"])
            cycle_state = harness.container.memory_assets.latest_retro_cycle_state(trade_day_utc=now.date().isoformat())
            self.assertIsNotNone(cycle_state)
            self.assertEqual(cycle_state["state"], "chief_pending")
            self.assertEqual(sorted(cycle_state["ready_brief_roles"]), ["macro_event_analyst", "pm", "risk_trader"])
            self.assertEqual(cycle_state["missing_brief_roles"], [])
            self.assertEqual(cycle_state["chief_dispatch_status"], "dispatched")
            pack = harness.container.agent_gateway.pull_chief_retro_pack(trigger_type="daily_retro")
            self.assertEqual(pack.payload["retro_cycle_state"]["cycle_id"], cycle_state["cycle_id"])
            self.assertEqual(pack.payload["retro_case"]["case_id"], result["case_id"])
            self.assertEqual(len(pack.payload["retro_briefs"]), 3)
            self.assertEqual(pack.payload["pending_retro_brief_roles"], [])
            self.assertTrue(pack.payload["retro_briefs_ready"])
            self.assertTrue(pack.payload["retro_ready_for_synthesis"])
        finally:
            harness.cleanup()

    def test_retro_prep_monitor_marks_degraded_after_brief_deadline_and_still_dispatches_chief(self) -> None:
        harness = build_test_harness()
        try:
            now = datetime(2026, 4, 12, 22, 45, tzinfo=UTC)
            cycle_state, retro_case = _seed_pending_retro_case(harness, trade_day_utc=now.date().isoformat())
            harness.container.memory_assets.materialize_retro_brief(
                trace_id="trace-retro-pm-brief",
                case_id=retro_case["case_id"],
                cycle_id=cycle_state["cycle_id"],
                agent_role="pm",
                authored_payload={
                    "root_cause": "PM 过度保守。",
                    "cross_role_challenge": "RT 需要更主动。",
                    "self_critique": "band 写得不够锋利。",
                    "tomorrow_change": "明天把边界写清楚。",
                },
            )
            harness.container.memory_assets.save_retro_cycle_state(
                trace_id="trace-retro-cycle-update",
                cycle_id=cycle_state["cycle_id"],
                payload={
                    **cycle_state,
                    "retro_case_id": retro_case["case_id"],
                    "brief_deadline_utc": (now - timedelta(minutes=1)).isoformat(),
                    "ready_brief_roles": ["pm"],
                    "missing_brief_roles": ["risk_trader", "macro_event_analyst"],
                },
            )
            monitor, runner = _build_retro_prep_monitor(harness)
            result = monitor.scan_once(now=now)
            self.assertTrue(result["triggered"])
            self.assertEqual(result["status"], "degraded")
            self.assertTrue(result["chief_dispatched"])
            self.assertEqual(runner.runs, ["chief-job"])
            cycle_state = harness.container.memory_assets.latest_retro_cycle_state(trade_day_utc=now.date().isoformat())
            self.assertEqual(cycle_state["state"], "degraded")
            self.assertEqual(cycle_state["degraded_reason"], "missing_briefs")
            self.assertEqual(cycle_state["ready_brief_roles"], ["pm"])
            self.assertEqual(sorted(cycle_state["missing_brief_roles"]), ["macro_event_analyst", "risk_trader"])
        finally:
            harness.cleanup()

    def test_retro_prep_monitor_does_not_redispatch_same_cycle(self) -> None:
        harness = build_test_harness()
        try:
            monitor, runner = _build_retro_prep_monitor(harness)
            now = datetime(2026, 4, 12, 22, 45, tzinfo=UTC)
            first = monitor.scan_once(now=now)
            second = monitor.scan_once(now=now + timedelta(minutes=1))
            self.assertTrue(first["chief_dispatched"])
            self.assertFalse(second["chief_dispatched"])
            self.assertEqual(second["chief_dispatch_status"], "already_dispatched")
            self.assertEqual(runner.runs, ["chief-job"])
        finally:
            harness.cleanup()

    def test_retro_prep_monitor_marks_completed_after_chief_retro_exists(self) -> None:
        harness = build_test_harness()
        try:
            monitor, runner = _build_retro_prep_monitor(harness)
            now = datetime(2026, 4, 12, 22, 45, tzinfo=UTC)
            first = monitor.scan_once(now=now)
            harness.container.memory_assets.save_asset(
                asset_type="chief_retro",
                asset_id="chief-retro-1",
                trace_id="trace-chief-retro-done",
                actor_role="crypto_chief",
                payload={
                    "retro_id": "chief-retro-1",
                    "case_id": first["case_id"],
                    "owner_summary": "Chief retro completed.",
                    "learning_directives": [
                        {"agent_role": "pm", "directive": "pm directive", "rationale": "pm rationale"},
                        {"agent_role": "risk_trader", "directive": "rt directive", "rationale": "rt rationale"},
                        {"agent_role": "macro_event_analyst", "directive": "mea directive", "rationale": "mea rationale"},
                        {"agent_role": "crypto_chief", "directive": "chief directive", "rationale": "chief rationale"},
                    ],
                },
            )
            second = monitor.scan_once(now=now + timedelta(minutes=2))
            self.assertFalse(second["chief_dispatched"])
            self.assertEqual(second["status"], "completed")
            self.assertEqual(second["chief_dispatch_status"], "already_completed")
            self.assertEqual(runner.runs, ["chief-job"])
            cycle_state = harness.container.memory_assets.latest_retro_cycle_state(trade_day_utc=now.date().isoformat())
            self.assertEqual(cycle_state["state"], "completed")
        finally:
            harness.cleanup()

    def test_retro_prep_monitor_materializes_learning_directives_from_chief_retro(self) -> None:
        harness = build_test_harness()
        try:
            monitor, _runner = _build_retro_prep_monitor(harness)
            now = datetime(2026, 4, 12, 22, 45, tzinfo=UTC)
            first = monitor.scan_once(now=now)
            cycle_state = harness.container.memory_assets.latest_retro_cycle_state(trade_day_utc=now.date().isoformat())
            harness.container.memory_assets.save_asset(
                asset_type="chief_retro",
                asset_id="chief-retro-materialize",
                trace_id="trace-chief-retro-materialize",
                actor_role="crypto_chief",
                payload={
                    "retro_id": "chief-retro-materialize",
                    "case_id": first["case_id"],
                    "cycle_id": cycle_state["cycle_id"],
                    "owner_summary": "Chief retro completed.",
                    "learning_directives": [
                        {"agent_role": "pm", "directive": "pm directive", "rationale": "pm rationale"},
                        {"agent_role": "risk_trader", "directive": "rt directive", "rationale": "rt rationale"},
                        {"agent_role": "macro_event_analyst", "directive": "mea directive", "rationale": "mea rationale"},
                        {"agent_role": "crypto_chief", "directive": "chief directive", "rationale": "chief rationale"},
                    ],
                },
            )
            second = monitor.scan_once(now=now + timedelta(minutes=2))
            self.assertEqual(second["status"], "completed")
            directives = harness.container.memory_assets.get_learning_directives(
                case_id=first["case_id"],
                cycle_id=cycle_state["cycle_id"],
            )
            self.assertEqual(len(directives), 4)
            self.assertEqual({item["agent_role"] for item in directives}, {"pm", "risk_trader", "macro_event_analyst", "crypto_chief"})
            self.assertTrue(all(item["completion_state"] == "pending" for item in directives))
            chief_asset = harness.container.memory_assets.latest_asset(asset_type="chief_retro", actor_role="crypto_chief")
            self.assertEqual(len(chief_asset["payload"]["learning_directive_ids"]), 4)
        finally:
            harness.cleanup()

    def test_retro_prep_monitor_marks_failed_when_chief_learning_directives_missing_role(self) -> None:
        harness = build_test_harness()
        try:
            monitor, _runner = _build_retro_prep_monitor(harness)
            now = datetime(2026, 4, 12, 22, 45, tzinfo=UTC)
            first = monitor.scan_once(now=now)
            cycle_state = harness.container.memory_assets.latest_retro_cycle_state(trade_day_utc=now.date().isoformat())
            harness.container.memory_assets.save_asset(
                asset_type="chief_retro",
                asset_id="chief-retro-missing-role",
                trace_id="trace-chief-retro-missing-role",
                actor_role="crypto_chief",
                payload={
                    "retro_id": "chief-retro-missing-role",
                    "case_id": first["case_id"],
                    "cycle_id": cycle_state["cycle_id"],
                    "owner_summary": "Chief retro completed.",
                    "learning_directives": [
                        {"agent_role": "pm", "directive": "pm directive", "rationale": "pm rationale"},
                        {"agent_role": "risk_trader", "directive": "rt directive", "rationale": "rt rationale"},
                        {"agent_role": "macro_event_analyst", "directive": "mea directive", "rationale": "mea rationale"},
                    ],
                },
            )
            second = monitor.scan_once(now=now + timedelta(minutes=2))
            self.assertEqual(second["status"], "failed")
            cycle_state = harness.container.memory_assets.latest_retro_cycle_state(trade_day_utc=now.date().isoformat())
            self.assertEqual(cycle_state["state"], "failed")
            self.assertIn("missing_learning_directives:crypto_chief", str(cycle_state["degraded_reason"]))
            directives = harness.container.memory_assets.get_learning_directives(
                case_id=first["case_id"],
                cycle_id=cycle_state["cycle_id"],
            )
            self.assertEqual(directives, [])
        finally:
            harness.cleanup()

    def test_retro_prep_monitor_marks_learning_directive_completed_from_file_facts(self) -> None:
        harness = build_test_harness()
        try:
            monitor, _runner = _build_retro_prep_monitor(harness)
            now = datetime(2026, 4, 12, 22, 45, tzinfo=UTC)
            learning_path = Path(harness.container.agent_gateway.learning_path_by_role["pm"])
            learning_path.parent.mkdir(parents=True, exist_ok=True)
            learning_path.write_text("baseline\n", encoding="utf-8")
            baseline = monitor._learning_file_fingerprint(str(learning_path))
            cycle_state, retro_case = _seed_pending_retro_case(harness, trade_day_utc=now.date().isoformat())
            directive = harness.container.memory_assets.materialize_learning_directive(
                trace_id="trace-learning-completed",
                case_id=retro_case["case_id"],
                cycle_id=cycle_state["cycle_id"],
                agent_role="pm",
                session_key="agent:pm:main",
                learning_path=str(learning_path),
                actor_role="system",
                authored_payload={
                    "directive": "pm directive",
                    "rationale": "pm rationale",
                    "baseline_fingerprint": baseline,
                    "completion_state": "pending",
                },
            )
            learning_path.write_text("baseline\nupdated\n", encoding="utf-8")
            monitor.scan_once(now=now, force=True)
            updated = next(
                item
                for item in harness.container.memory_assets.get_learning_directives(case_id=retro_case["case_id"])
                if item["directive_id"] == directive["directive_id"]
            )
            self.assertEqual(updated["completion_state"], "completed")
            self.assertIsNotNone(updated["completed_at_utc"])
        finally:
            harness.cleanup()

    def test_retro_prep_monitor_marks_learning_directive_stale_from_file_facts(self) -> None:
        harness = build_test_harness()
        try:
            monitor, _runner = _build_retro_prep_monitor(harness)
            now = datetime(2026, 4, 12, 22, 45, tzinfo=UTC)
            learning_path = Path(harness.container.agent_gateway.learning_path_by_role["risk_trader"])
            learning_path.parent.mkdir(parents=True, exist_ok=True)
            learning_path.write_text("baseline\n", encoding="utf-8")
            baseline = monitor._learning_file_fingerprint(str(learning_path))
            cycle_state, retro_case = _seed_pending_retro_case(harness, trade_day_utc=now.date().isoformat())
            directive = harness.container.memory_assets.materialize_learning_directive(
                trace_id="trace-learning-stale",
                case_id=retro_case["case_id"],
                cycle_id=cycle_state["cycle_id"],
                agent_role="risk_trader",
                session_key="agent:risk_trader:main",
                learning_path=str(learning_path),
                actor_role="system",
                authored_payload={
                    "directive": "rt directive",
                    "rationale": "rt rationale",
                    "baseline_fingerprint": baseline,
                    "completion_state": "pending",
                },
            )
            learning_path.unlink()
            monitor.scan_once(now=now, force=True)
            updated = next(
                item
                for item in harness.container.memory_assets.get_learning_directives(case_id=retro_case["case_id"])
                if item["directive_id"] == directive["directive_id"]
            )
            self.assertEqual(updated["completion_state"], "stale")
            self.assertIsNone(updated["completed_at_utc"])
        finally:
            harness.cleanup()

    def test_retro_prep_monitor_stays_idle_before_window(self) -> None:
        harness = build_test_harness()
        try:
            monitor, runner = _build_retro_prep_monitor(harness)
            now = datetime(2026, 4, 12, 22, 20, tzinfo=UTC)
            result = monitor.scan_once(now=now)
            self.assertFalse(result["triggered"])
            self.assertEqual(result["reason"], "outside_prep_window")
            self.assertEqual(runner.runs, [])
            pack = harness.container.agent_gateway.pull_chief_retro_pack(trigger_type="daily_retro")
            self.assertEqual(pack.payload["retro_case"], {})
            self.assertEqual(pack.payload["retro_briefs"], [])
            self.assertFalse(pack.payload["retro_ready_for_synthesis"])
        finally:
            harness.cleanup()

    def test_openclaw_cron_runner_detects_running_disabled_job_from_tasks_stderr(self) -> None:
        tasks_json = (
            '{"count":1,"tasks":[{"sourceId":"rt-job","status":"running","label":"rt-15m"}]}'
        )
        with patch(
            "openclaw_trader.modules.workflow_orchestrator.rt_trigger.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=tasks_json),
        ) as run:
            self.assertTrue(OpenClawCronRunner(openclaw_bin="openclaw").is_running(job_id="rt-job"))
        self.assertEqual(run.call_args.args[0], ["openclaw", "tasks", "--json", "list", "--runtime", "cron", "--status", "running"])

    def test_openclaw_cron_runner_falls_back_to_cron_list_all_state(self) -> None:
        tasks_json = '{"count":0,"tasks":[]}'
        cron_json = '{"jobs":[{"id":"rt-job","state":{"runningAtMs":1775579754486}}]}'
        with patch(
            "openclaw_trader.modules.workflow_orchestrator.rt_trigger.subprocess.run",
            side_effect=[
                subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=tasks_json),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=cron_json, stderr=""),
            ],
        ) as run:
            self.assertTrue(OpenClawCronRunner(openclaw_bin="openclaw").is_running(job_id="rt-job"))
        self.assertEqual(run.call_args_list[1].args[0], ["openclaw", "cron", "list", "--all", "--json"])

    def test_rt_trigger_strategy_revision_runs_standard_rt_cron_once(self) -> None:
        harness = build_test_harness()
        try:
            now = datetime(2026, 4, 7, 1, 0, tzinfo=UTC)
            _seed_strategy(harness)
            monitor, runner = _build_monitor(harness)
            result = monitor.scan_once(now=now)
            self.assertEqual(result["reason"], "pm_strategy_update")
            self.assertTrue(result["dispatched"])
            self.assertEqual(runner.runs, ["rt-job"])

            runner.runs.clear()
            second = monitor.scan_once(now=now + timedelta(minutes=1))
            self.assertFalse(second["triggered"])
            self.assertEqual(runner.runs, [])
        finally:
            harness.cleanup()

    def test_rt_trigger_high_news_respects_cooldown_but_critical_bypasses_it(self) -> None:
        harness = build_test_harness()
        try:
            now = datetime(2026, 4, 7, 1, 0, tzinfo=UTC)
            _seed_trigger_state(harness, {"last_trigger_at_utc": now.isoformat()})
            harness.container.memory_assets.save_asset(
                asset_type="news_submission",
                actor_role="macro_event_analyst",
                payload={"events": [{"event_id": "evt-high", "impact_level": "high", "summary": "High risk."}]},
            )
            monitor, runner = _build_monitor(harness)
            high_result = monitor.scan_once(now=now + timedelta(minutes=1))
            self.assertEqual(high_result["reason"], "mea_high_impact_event")
            self.assertEqual(high_result["skipped_reason"], "global_cooldown")
            self.assertEqual(runner.runs, [])

            harness.container.memory_assets.save_asset(
                asset_type="news_submission",
                actor_role="macro_event_analyst",
                payload={"events": [{"event_id": "evt-critical", "impact_level": "critical", "summary": "Critical risk."}]},
            )
            critical_result = monitor.scan_once(now=now + timedelta(minutes=2))
            self.assertEqual(critical_result["severity"], "critical")
            self.assertTrue(critical_result["dispatched"])
            self.assertEqual(runner.runs, ["rt-job"])
        finally:
            harness.cleanup()

    def test_rt_trigger_medium_news_alone_does_not_wake_rt(self) -> None:
        harness = build_test_harness()
        try:
            now = datetime(2026, 4, 7, 1, 0, tzinfo=UTC)
            _seed_trigger_state(harness, {"last_trigger_at_utc": (now - timedelta(minutes=10)).isoformat()})
            harness.container.memory_assets.save_asset(
                asset_type="news_submission",
                actor_role="macro_event_analyst",
                payload={"events": [{"event_id": "evt-medium", "impact_level": "medium", "summary": "Medium event."}]},
            )
            monitor, runner = _build_monitor(harness)
            result = monitor.scan_once(now=now + timedelta(minutes=1))
            self.assertFalse(result["triggered"])
            self.assertEqual(runner.runs, [])
        finally:
            harness.cleanup()

    def test_rt_trigger_market_structure_only_checks_eligible_coins(self) -> None:
        harness = build_test_harness()
        try:
            now = datetime(2026, 4, 7, 1, 0, tzinfo=UTC)
            strategy = _seed_strategy(
                harness,
                targets=[
                    {
                        "symbol": "BTC",
                        "state": "active",
                        "direction": "long",
                        "target_exposure_band_pct": [0.0, 10.0],
                        "rt_discretion_band_pct": 2.0,
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
                ],
            )
            provider = MutableMarketDataProvider()
            provider.breakout_by_coin = {"BTC": "up_breakout", "ETH": "up_breakout"}
            _seed_trigger_state(
                harness,
                {
                    "last_seen_strategy_key": _strategy_key(strategy),
                    "last_trigger_at_utc": (now - timedelta(hours=2)).isoformat(),
                    "last_market_state_by_coin": {
                        "BTC": {"mark_price": 100.0, "breakout_state": "range", "volatility_state": "normal"},
                        "ETH": {"mark_price": 100.0, "breakout_state": "range", "volatility_state": "normal"},
                    },
                },
            )
            monitor, runner = _build_monitor(harness, provider=provider)
            result = monitor.scan_once(now=now)
            self.assertEqual(result["reason"], "market_structure_change")
            self.assertEqual(result["coins"], ["BTC"])
            self.assertEqual(runner.runs, ["rt-job"])
        finally:
            harness.cleanup()

    def test_rt_trigger_ignores_flat_watch_breakout_without_position(self) -> None:
        harness = build_test_harness()
        try:
            now = datetime(2026, 4, 7, 1, 0, tzinfo=UTC)
            strategy = _seed_strategy(
                harness,
                targets=[
                    {
                        "symbol": "ETH",
                        "state": "watch",
                        "direction": "flat",
                        "target_exposure_band_pct": [0.0, 0.0],
                        "rt_discretion_band_pct": 0.0,
                        "priority": 2,
                    }
                ],
            )
            provider = MutableMarketDataProvider()
            provider.flat = True
            provider.breakout_by_coin = {"ETH": "up_breakout"}
            _seed_trigger_state(
                harness,
                {
                    "last_seen_strategy_key": _strategy_key(strategy),
                    "last_trigger_at_utc": now.isoformat(),
                    "last_market_state_by_coin": {
                        "ETH": {"mark_price": 100.0, "breakout_state": "range", "volatility_state": "normal"},
                    },
                },
            )
            monitor, runner = _build_monitor(harness, provider=provider)
            result = monitor.scan_once(now=now + timedelta(minutes=1))
            self.assertFalse(result["triggered"])
            self.assertEqual(runner.runs, [])
        finally:
            harness.cleanup()

    def test_rt_trigger_exposure_drift_wakes_rt(self) -> None:
        harness = build_test_harness()
        try:
            now = datetime(2026, 4, 7, 1, 0, tzinfo=UTC)
            strategy = _seed_strategy(
                harness,
                gross_band=[40.0, 70.0],
                targets=[
                    {
                        "symbol": "BTC",
                        "state": "active",
                        "direction": "long",
                        "target_exposure_band_pct": [30.0, 50.0],
                        "rt_discretion_band_pct": 2.0,
                        "priority": 1,
                    }
                ],
            )
            _seed_trigger_state(
                harness,
                {
                    "last_seen_strategy_key": _strategy_key(strategy),
                    "last_trigger_at_utc": now.isoformat(),
                },
            )
            monitor, runner = _build_monitor(harness)
            result = monitor.scan_once(now=now + timedelta(minutes=10))
            self.assertEqual(result["reason"], "exposure_drift")
            self.assertTrue(result["dispatched"])
            self.assertEqual(runner.runs, ["rt-job"])
        finally:
            harness.cleanup()

    def test_rt_trigger_execution_followup_runs_once(self) -> None:
        harness = build_test_harness()
        try:
            now = datetime(2026, 4, 7, 1, 0, tzinfo=UTC)
            _seed_trigger_state(harness, {"last_trigger_at_utc": (now - timedelta(minutes=10)).isoformat()})
            harness.container.memory_assets.save_asset(
                asset_type="execution_result",
                actor_role="risk_trader",
                payload={
                    "decision_id": "decision-1",
                    "coin": "BTC",
                    "success": True,
                    "executed_at": (now - timedelta(minutes=4)).isoformat(),
                    "exchange_order_id": "order-1",
                    "fills": [{"price": "100", "size": "1"}],
                },
            )
            monitor, runner = _build_monitor(harness)
            result = monitor.scan_once(now=now)
            self.assertEqual(result["reason"], "execution_followup")
            self.assertEqual(runner.runs, ["rt-job"])

            runner.runs.clear()
            second = monitor.scan_once(now=now + timedelta(minutes=20))
            self.assertNotEqual(second.get("reason"), "execution_followup")
            self.assertEqual(runner.runs, [])
        finally:
            harness.cleanup()

    def test_rt_trigger_hourly_limit_blocks_normal_triggers(self) -> None:
        harness = build_test_harness()
        try:
            now = datetime(2026, 4, 7, 1, 0, tzinfo=UTC)
            strategy = _seed_strategy(harness, gross_band=[40.0, 70.0])
            _seed_trigger_state(
                harness,
                {
                    "last_seen_strategy_key": _strategy_key(strategy),
                    "last_trigger_at_utc": (now - timedelta(minutes=10)).isoformat(),
                    "recent_trigger_times_utc": [
                        (now - timedelta(minutes=50)).isoformat(),
                        (now - timedelta(minutes=40)).isoformat(),
                        (now - timedelta(minutes=30)).isoformat(),
                        (now - timedelta(minutes=20)).isoformat(),
                    ],
                },
            )
            monitor, runner = _build_monitor(harness)
            result = monitor.scan_once(now=now)
            self.assertEqual(result["reason"], "exposure_drift")
            self.assertEqual(result["skipped_reason"], "hourly_limit")
            self.assertEqual(runner.runs, [])
        finally:
            harness.cleanup()

    def test_rt_trigger_heartbeat_uses_position_and_flat_intervals(self) -> None:
        harness = build_test_harness()
        try:
            now = datetime(2026, 4, 7, 1, 0, tzinfo=UTC)
            _seed_trigger_state(harness, {"last_trigger_at_utc": (now - timedelta(minutes=61)).isoformat()})
            monitor, runner = _build_monitor(harness)
            position_result = monitor.scan_once(now=now)
            self.assertEqual(position_result["reason"], "heartbeat")
            self.assertEqual(runner.runs, ["rt-job"])
        finally:
            harness.cleanup()

        harness = build_test_harness()
        try:
            now = datetime(2026, 4, 7, 1, 0, tzinfo=UTC)
            provider = MutableMarketDataProvider()
            provider.flat = True
            _seed_trigger_state(harness, {"last_trigger_at_utc": (now - timedelta(minutes=119)).isoformat()})
            monitor, runner = _build_monitor(harness, provider=provider)
            flat_result = monitor.scan_once(now=now)
            self.assertFalse(flat_result["triggered"])
            self.assertEqual(runner.runs, [])

            flat_result = monitor.scan_once(now=now + timedelta(minutes=2))
            self.assertEqual(flat_result["reason"], "heartbeat")
            self.assertEqual(runner.runs, ["rt-job"])
        finally:
            harness.cleanup()

    def test_rt_trigger_skips_when_openclaw_cron_job_is_already_running(self) -> None:
        harness = build_test_harness()
        try:
            now = datetime(2026, 4, 7, 1, 0, tzinfo=UTC)
            _seed_strategy(harness)
            monitor, runner = _build_monitor(harness)
            runner.running = True
            result = monitor.scan_once(now=now)
            self.assertEqual(result["reason"], "pm_strategy_update")
            self.assertEqual(result["skipped_reason"], "cron_running")
            self.assertEqual(runner.runs, [])
        finally:
            harness.cleanup()

    def test_risk_brake_portfolio_reduce_cuts_half_and_pings_pm_only(self) -> None:
        """Portfolio reduce auto-executes a 50% cut on losing positions and
        dispatches ONLY PM — RT isn't re-woken because the system already
        placed the safety order itself."""
        harness = build_test_harness()
        try:
            now = datetime(2026, 4, 8, 14, 0, tzinfo=UTC)
            provider = MutableMarketDataProvider()
            provider.unrealized_pnl_usd = "-20"
            provider.portfolio_total_equity_usd = "1000"
            _seed_strategy(harness)
            _seed_risk_brake_state(
                harness,
                {
                    "portfolio_day_utc": now.date().isoformat(),
                    "portfolio_day_peak_equity_usd": "1025",
                    "last_portfolio_state": "normal",
                    "last_position_state_by_coin": {"BTC": "normal"},
                },
            )
            monitor, runner = _build_risk_brake_monitor(harness, provider=provider)
            result = monitor.scan_once(now=now)

            self.assertTrue(result["triggered"])
            self.assertEqual(result["scope"], "portfolio")
            self.assertEqual(result["state"], "reduce")
            self.assertFalse(result["rt_dispatched"])
            self.assertTrue(result["pm_dispatched"])
            self.assertEqual(runner.runs, ["pm-job"])
            self.assertTrue(str(result["pm_trigger_event_id"]).startswith("pm_trigger"))
            self.assertEqual(len(harness.fake_broker.executed), 1)
            self.assertEqual(harness.fake_broker.executed[0].action, "reduce")
            self.assertEqual(harness.fake_broker.executed[0].coin, "BTC")
            self.assertEqual(harness.fake_broker.executed[0].notional_usd, "100")

            state_asset = harness.container.memory_assets.get_asset("risk_brake_state")
            self.assertEqual(state_asset["payload"]["portfolio_lock"]["mode"], "reduce_only")
            batch_asset = harness.container.memory_assets.latest_asset(asset_type="execution_batch", actor_role="system")
            self.assertIsNotNone(batch_asset)
            self.assertTrue(str(batch_asset["payload"]["decision_id"]).startswith("risk_reduce_"))
            pm_trigger_asset = harness.container.memory_assets.latest_asset(asset_type="pm_trigger_event", actor_role="system")
            self.assertIsNotNone(pm_trigger_asset)
            self.assertEqual(pm_trigger_asset["payload"]["trigger_type"], "risk_brake")
            self.assertEqual(pm_trigger_asset["payload"]["reason"], "portfolio_peak_reduce")
            self.assertTrue(pm_trigger_asset["payload"]["claimable"])
        finally:
            harness.cleanup()

    def test_risk_brake_portfolio_observe_pings_rt_only(self) -> None:
        """The observe line is an early warning: no auto-order, no portfolio
        lock, no PM dispatch — only RT gets nudged so the tactical map can
        be refreshed before things get worse."""
        harness = build_test_harness()
        try:
            now = datetime(2026, 4, 8, 14, 0, tzinfo=UTC)
            provider = MutableMarketDataProvider()
            # Peak=1025, current=1012 → drawdown 1.27%, above observe (1.2%)
            # but below reduce (2.0%).
            provider.portfolio_total_equity_usd = "1012"
            provider.unrealized_pnl_usd = "-1"
            _seed_strategy(harness)
            _seed_risk_brake_state(
                harness,
                {
                    "portfolio_day_utc": now.date().isoformat(),
                    "portfolio_day_peak_equity_usd": "1025",
                    "last_portfolio_state": "normal",
                    "portfolio_state_ladder_high": "normal",
                    "last_position_state_by_coin": {"BTC": "normal"},
                },
            )
            monitor, runner = _build_risk_brake_monitor(harness, provider=provider)
            result = monitor.scan_once(now=now)

            self.assertTrue(result["triggered"])
            self.assertEqual(result["scope"], "portfolio")
            self.assertEqual(result["state"], "observe")
            self.assertTrue(result["rt_dispatched"])
            self.assertFalse(result["pm_dispatched"])
            self.assertEqual(runner.runs, ["rt-job"])
            self.assertNotIn("pm_trigger_event_id", result)
            # No auto-order, no portfolio lock.
            self.assertEqual(len(harness.fake_broker.executed), 0)
            state_asset = harness.container.memory_assets.get_asset("risk_brake_state")
            self.assertEqual(state_asset["payload"].get("portfolio_lock") or {}, {})
            # Ladder ratcheted to observe so subsequent small dips don't re-fire.
            self.assertEqual(state_asset["payload"]["portfolio_state_ladder_high"], "observe")
        finally:
            harness.cleanup()

    def test_risk_brake_portfolio_exit_closes_all_and_pings_pm_only(self) -> None:
        """Exit liquidates every open position and dispatches only PM. No RT
        — RT has nothing left to decide; PM gets woken to rebuild the
        plan from scratch."""
        harness = build_test_harness()
        try:
            now = datetime(2026, 4, 8, 14, 0, tzinfo=UTC)
            provider = MutableMarketDataProvider()
            # Peak=1025, current=985 → drawdown 3.9%, above exit (3.2%).
            provider.portfolio_total_equity_usd = "985"
            provider.unrealized_pnl_usd = "-5"
            _seed_strategy(harness)
            _seed_risk_brake_state(
                harness,
                {
                    "portfolio_day_utc": now.date().isoformat(),
                    "portfolio_day_peak_equity_usd": "1025",
                    "last_portfolio_state": "normal",
                    "portfolio_state_ladder_high": "normal",
                    "last_position_state_by_coin": {"BTC": "normal"},
                },
            )
            monitor, runner = _build_risk_brake_monitor(harness, provider=provider)
            result = monitor.scan_once(now=now)

            self.assertTrue(result["triggered"])
            self.assertEqual(result["scope"], "portfolio")
            self.assertEqual(result["state"], "exit")
            self.assertFalse(result["rt_dispatched"])
            self.assertTrue(result["pm_dispatched"])
            self.assertEqual(runner.runs, ["pm-job"])
            self.assertEqual(len(harness.fake_broker.executed), 1)
            self.assertEqual(harness.fake_broker.executed[0].action, "close")
            state_asset = harness.container.memory_assets.get_asset("risk_brake_state")
            self.assertEqual(state_asset["payload"]["portfolio_lock"]["mode"], "flat_only")
            self.assertEqual(state_asset["payload"]["portfolio_state_ladder_high"], "exit")
            pm_trigger_asset = harness.container.memory_assets.latest_asset(asset_type="pm_trigger_event", actor_role="system")
            self.assertIsNotNone(pm_trigger_asset)
            self.assertEqual(pm_trigger_asset["payload"]["lock_mode"], "flat_only")
        finally:
            harness.cleanup()

    def test_risk_brake_position_exit_closes_coin_and_pings_pm_only(self) -> None:
        """Per-coin exit follows the same dispatch policy as portfolio exit:
        auto-close the coin and ping only PM."""
        harness = build_test_harness()
        try:
            now = datetime(2026, 4, 8, 14, 0, tzinfo=UTC)
            provider = MutableMarketDataProvider()
            provider.mark_by_coin["BTC"] = "92"
            _seed_strategy(harness)
            _seed_risk_brake_state(
                harness,
                {
                    "portfolio_day_utc": now.date().isoformat(),
                    "portfolio_day_peak_equity_usd": "1000",
                    "last_portfolio_state": "normal",
                    "last_position_state_by_coin": {"BTC": "normal"},
                    "position_references_by_coin": {
                        "BTC": {
                            "side": "long",
                            "reference_price": "100",
                            "reference_kind": "peak",
                        }
                    },
                },
            )
            monitor, runner = _build_risk_brake_monitor(harness, provider=provider)
            result = monitor.scan_once(now=now)

            self.assertTrue(result["triggered"])
            self.assertEqual(result["scope"], "position")
            self.assertEqual(result["state"], "exit")
            self.assertFalse(result["rt_dispatched"])
            self.assertTrue(result["pm_dispatched"])
            self.assertEqual(runner.runs, ["pm-job"])
            self.assertEqual(len(harness.fake_broker.executed), 1)
            self.assertEqual(harness.fake_broker.executed[0].action, "close")
            state_asset = harness.container.memory_assets.get_asset("risk_brake_state")
            self.assertEqual(state_asset["payload"]["position_locks"]["BTC"]["mode"], "flat_only")
            self.assertEqual(state_asset["payload"]["position_state_ladder_high_by_coin"]["BTC"], "exit")
            pm_trigger_asset = harness.container.memory_assets.latest_asset(asset_type="pm_trigger_event", actor_role="system")
            self.assertIsNotNone(pm_trigger_asset)
            self.assertEqual(pm_trigger_asset["payload"]["reason"], "position_peak_exit")
            self.assertEqual(pm_trigger_asset["payload"]["lock_mode"], "flat_only")
        finally:
            harness.cleanup()

    def test_risk_brake_position_observe_pings_rt_only(self) -> None:
        """Per-coin observe: heads-up only. No auto-order, no position lock,
        no PM dispatch — mirrors portfolio observe."""
        harness = build_test_harness()
        try:
            now = datetime(2026, 4, 8, 14, 0, tzinfo=UTC)
            provider = MutableMarketDataProvider()
            # Reference=100, mark=98.3 → drawdown 1.7% > position_observe
            # (1.6%) but < position_reduce (2.8%) and < position_exit (4.0%).
            provider.mark_by_coin["BTC"] = "98.3"
            _seed_strategy(harness)
            _seed_risk_brake_state(
                harness,
                {
                    "portfolio_day_utc": now.date().isoformat(),
                    "portfolio_day_peak_equity_usd": "1000",
                    "last_portfolio_state": "normal",
                    "portfolio_state_ladder_high": "normal",
                    "last_position_state_by_coin": {"BTC": "normal"},
                    "position_state_ladder_high_by_coin": {"BTC": "normal"},
                    "position_references_by_coin": {
                        "BTC": {
                            "side": "long",
                            "reference_price": "100",
                            "reference_kind": "peak",
                        }
                    },
                },
            )
            monitor, runner = _build_risk_brake_monitor(harness, provider=provider)
            result = monitor.scan_once(now=now)

            self.assertTrue(result["triggered"])
            self.assertEqual(result["scope"], "position")
            self.assertEqual(result["state"], "observe")
            self.assertTrue(result["rt_dispatched"])
            self.assertFalse(result["pm_dispatched"])
            self.assertEqual(runner.runs, ["rt-job"])
            self.assertNotIn("pm_trigger_event_id", result)
            # No auto-order, no per-coin lock.
            self.assertEqual(len(harness.fake_broker.executed), 0)
            state_asset = harness.container.memory_assets.get_asset("risk_brake_state")
            self.assertEqual(state_asset["payload"].get("position_locks") or {}, {})
            self.assertEqual(
                state_asset["payload"]["position_state_ladder_high_by_coin"]["BTC"], "observe"
            )
        finally:
            harness.cleanup()

    def test_risk_brake_position_reduce_cuts_coin_and_pings_pm_only(self) -> None:
        """Per-coin reduce: auto 50% cut, PM only."""
        harness = build_test_harness()
        try:
            now = datetime(2026, 4, 8, 14, 0, tzinfo=UTC)
            provider = MutableMarketDataProvider()
            # Reference=100, mark=97.0 → drawdown 3.0% > position_reduce
            # (2.8%) but < position_exit (4.0%).
            provider.mark_by_coin["BTC"] = "97.0"
            _seed_strategy(harness)
            _seed_risk_brake_state(
                harness,
                {
                    "portfolio_day_utc": now.date().isoformat(),
                    "portfolio_day_peak_equity_usd": "1000",
                    "last_portfolio_state": "normal",
                    "portfolio_state_ladder_high": "normal",
                    "last_position_state_by_coin": {"BTC": "normal"},
                    "position_state_ladder_high_by_coin": {"BTC": "normal"},
                    "position_references_by_coin": {
                        "BTC": {
                            "side": "long",
                            "reference_price": "100",
                            "reference_kind": "peak",
                        }
                    },
                },
            )
            monitor, runner = _build_risk_brake_monitor(harness, provider=provider)
            result = monitor.scan_once(now=now)

            self.assertTrue(result["triggered"])
            self.assertEqual(result["scope"], "position")
            self.assertEqual(result["state"], "reduce")
            self.assertFalse(result["rt_dispatched"])
            self.assertTrue(result["pm_dispatched"])
            self.assertEqual(runner.runs, ["pm-job"])
            self.assertEqual(len(harness.fake_broker.executed), 1)
            self.assertEqual(harness.fake_broker.executed[0].action, "reduce")
            state_asset = harness.container.memory_assets.get_asset("risk_brake_state")
            self.assertEqual(state_asset["payload"]["position_locks"]["BTC"]["mode"], "reduce_only")
            self.assertEqual(
                state_asset["payload"]["position_state_ladder_high_by_coin"]["BTC"], "reduce"
            )
        finally:
            harness.cleanup()

    def test_risk_brake_does_not_refire_after_equity_recovery_within_day(self) -> None:
        """Once 'reduce' has been crossed today, dipping back to reduce must not
        re-fire the event / re-dispatch RT+PM. Without the sticky
        portfolio_state_ladder_high, last_portfolio_state would oscillate between
        normal and reduce as equity flaps around the line, firing every dip."""
        harness = build_test_harness()
        try:
            now = datetime(2026, 4, 8, 14, 0, tzinfo=UTC)
            provider = MutableMarketDataProvider()
            provider.unrealized_pnl_usd = "-20"
            provider.portfolio_total_equity_usd = "1000"
            _seed_strategy(harness)
            _seed_risk_brake_state(
                harness,
                {
                    "portfolio_day_utc": now.date().isoformat(),
                    "portfolio_day_peak_equity_usd": "1025",
                    # Equity recovered earlier this day, so last_portfolio_state
                    # is back to "normal" — but the ladder retains the worst-so-far.
                    "last_portfolio_state": "normal",
                    "portfolio_state_ladder_high": "reduce",
                    # Position-level ladder is scoped out of this change — seed
                    # it as already-reduce so the position path also no-ops and
                    # we can isolate the portfolio-level suppression assertion.
                    "last_position_state_by_coin": {"BTC": "reduce"},
                    # Lock from the earlier fire is still in place.
                    "portfolio_lock": {
                        "mode": "reduce_only",
                        "strategy_key": "strategy_seeded:1",
                        "triggered_at_utc": now.isoformat(),
                    },
                },
            )
            monitor, runner = _build_risk_brake_monitor(harness, provider=provider)
            result = monitor.scan_once(now=now)

            self.assertFalse(result["triggered"])
            self.assertEqual(runner.runs, [])
            self.assertEqual(len(harness.fake_broker.executed), 0)

            state_asset = harness.container.memory_assets.get_asset("risk_brake_state")
            # ladder_high remains at reduce; it must not downgrade on recovery.
            self.assertEqual(state_asset["payload"]["portfolio_state_ladder_high"], "reduce")
        finally:
            harness.cleanup()

    def test_risk_brake_ladder_high_ratchets_upward_on_first_fire(self) -> None:
        """After a first crossing of the reduce line, portfolio_state_ladder_high
        should be bumped to 'reduce' so future dips at the same level are ignored."""
        harness = build_test_harness()
        try:
            now = datetime(2026, 4, 8, 14, 0, tzinfo=UTC)
            provider = MutableMarketDataProvider()
            provider.unrealized_pnl_usd = "-20"
            provider.portfolio_total_equity_usd = "1000"
            _seed_strategy(harness)
            _seed_risk_brake_state(
                harness,
                {
                    "portfolio_day_utc": now.date().isoformat(),
                    "portfolio_day_peak_equity_usd": "1025",
                    "last_portfolio_state": "normal",
                    "portfolio_state_ladder_high": "normal",
                    "last_position_state_by_coin": {"BTC": "normal"},
                },
            )
            monitor, _ = _build_risk_brake_monitor(harness, provider=provider)
            result = monitor.scan_once(now=now)
            self.assertTrue(result["triggered"])
            self.assertEqual(result["state"], "reduce")
            state_asset = harness.container.memory_assets.get_asset("risk_brake_state")
            self.assertEqual(state_asset["payload"]["portfolio_state_ladder_high"], "reduce")
        finally:
            harness.cleanup()

    def test_risk_brake_ladder_high_resets_at_utc_rollover(self) -> None:
        """A new UTC day wipes the day-peak and the ladder_high so yesterday's
        triggers don't bleed into today's decisions."""
        harness = build_test_harness()
        try:
            # State was last written yesterday with ladder_high=reduce.
            yesterday = datetime(2026, 4, 7, 23, 50, tzinfo=UTC)
            today = datetime(2026, 4, 8, 0, 10, tzinfo=UTC)
            provider = MutableMarketDataProvider()
            provider.unrealized_pnl_usd = "0"
            provider.portfolio_total_equity_usd = "1000"
            _seed_strategy(harness)
            _seed_risk_brake_state(
                harness,
                {
                    "portfolio_day_utc": yesterday.date().isoformat(),
                    "portfolio_day_peak_equity_usd": "1025",
                    "last_portfolio_state": "reduce",
                    "portfolio_state_ladder_high": "reduce",
                },
            )
            monitor, _ = _build_risk_brake_monitor(harness, provider=provider)
            monitor.scan_once(now=today)

            state_asset = harness.container.memory_assets.get_asset("risk_brake_state")
            self.assertEqual(state_asset["payload"]["portfolio_day_utc"], today.date().isoformat())
            # After reset, a fresh scan with normal equity keeps ladder at normal.
            self.assertEqual(state_asset["payload"]["portfolio_state_ladder_high"], "normal")
        finally:
            harness.cleanup()


class FakeAgentDispatcher:
    def __init__(self, *, payload_by_job: dict[str, str] | None = None) -> None:
        self.payload_by_job = dict(payload_by_job or {})
        self.sends: list[dict[str, object]] = []

    def send_to_session(self, *, agent, session_key, message, thinking=None, turn_timeout_seconds=None):
        from openclaw_trader.modules.workflow_orchestrator.agent_dispatch import DispatchResult

        self.sends.append(
            {
                "agent": agent,
                "session_key": session_key,
                "message": message,
                "thinking": thinking,
                "turn_timeout_seconds": turn_timeout_seconds,
            }
        )
        return DispatchResult(ok=True, pid=99999)

    def run_cron_job_detached(self, *, job_id):
        from openclaw_trader.modules.workflow_orchestrator.agent_dispatch import DispatchResult

        return DispatchResult(ok=True, pid=99999)

    def fetch_cron_job_payload_message(self, *, job_id):
        return self.payload_by_job.get(job_id)


def _pm_wake_rule(job_id: str = "pm-job-abc"):
    from openclaw_trader.modules.workflow_orchestrator.agent_wake import (
        AgentWakeRuleConfig,
        CronTimePredicateConfig,
        MaxSilencePredicateConfig,
        MessageSourceConfig,
    )

    return AgentWakeRuleConfig(
        name="pm_main_heartbeat",
        agent="pm",
        target_session_key="agent:pm:main",
        message_source=MessageSourceConfig(kind="cron_job_payload", job_id=job_id),
        fire_when_any_of=(
            CronTimePredicateConfig(kind="cron_time", expr="0 1 * * *", tz="UTC"),
            MaxSilencePredicateConfig(kind="max_silence_since", measure="last_strategy_submit", hours=12.0),
        ),
        cooldown_minutes=30,
        enabled=True,
    )


def _build_agent_wake_monitor(harness, *, rule=None, payload="run pm cron msg"):
    from openclaw_trader.modules.workflow_orchestrator.agent_wake import AgentWakeMonitor, AgentWakeSettings

    rule = rule or _pm_wake_rule()
    dispatcher = FakeAgentDispatcher(payload_by_job={rule.message_source.job_id: payload})
    settings = AgentWakeSettings(enabled=True, scan_interval_seconds=60, rules=(rule,))
    monitor = AgentWakeMonitor(
        memory_assets=harness.container.memory_assets,
        dispatcher=dispatcher,
        settings=settings,
        event_bus=harness.event_bus,
    )
    return monitor, dispatcher


class AgentWakeMonitorTests(unittest.TestCase):
    def test_cron_time_fires_when_current_crosses_scheduled_moment(self) -> None:
        harness = build_test_harness()
        try:
            # Seed a fresh strategy so max_silence_since does not race cron_time.
            harness.container.memory_assets.save_asset(
                asset_type="strategy",
                payload={"strategy_id": "fresh_for_cron_test"},
                actor_role="pm",
                group_key="2026-04-17",
            )
            monitor, dispatcher = _build_agent_wake_monitor(harness)
            # First scan at 00:59 UTC establishes baseline (no fire).
            monitor.scan_once(now=datetime(2026, 4, 17, 0, 59, tzinfo=UTC))
            self.assertEqual(len(dispatcher.sends), 0)
            # Second scan at 01:02 UTC: candidate 01:00 falls in (last_eval, current] → fires
            result = monitor.scan_once(now=datetime(2026, 4, 17, 1, 2, tzinfo=UTC))
            self.assertEqual(len(dispatcher.sends), 1)
            send = dispatcher.sends[0]
            self.assertEqual(send["agent"], "pm")
            self.assertEqual(send["session_key"], "agent:pm:main")
            self.assertEqual(send["message"], "run pm cron msg")
            self.assertEqual(result["fire_count"], 1)
            self.assertEqual(result["fires"][0]["predicate"], "cron_time")
        finally:
            harness.cleanup()

    def test_max_silence_fires_when_last_strategy_older_than_threshold(self) -> None:
        harness = build_test_harness()
        try:
            # Seed a strategy 13h before the scan moment.
            stale_iso = (datetime(2026, 4, 17, 6, 0, tzinfo=UTC) - timedelta(hours=13)).isoformat()
            # Save directly to backdate created_at.
            harness.container.memory_assets.save_asset(
                asset_type="strategy",
                payload={"strategy_id": "strategy_legacy_for_silence_test"},
                actor_role="pm",
                group_key="2026-04-16",
            )
            # Override created_at to backdate via direct sqlite if needed — but
            # save_asset sets created_at=now. Instead, scan at now=stale+13h exactly.
            # We rely on save_asset having set created_at ~now; scan 13h from then.
            now = datetime.now(UTC) + timedelta(hours=13, minutes=5)
            monitor, dispatcher = _build_agent_wake_monitor(harness)
            result = monitor.scan_once(now=now)
            self.assertEqual(result["fire_count"], 1, result)
            self.assertEqual(result["fires"][0]["predicate"], "max_silence_since")
        finally:
            harness.cleanup()

    def test_cooldown_prevents_double_fire(self) -> None:
        harness = build_test_harness()
        try:
            harness.container.memory_assets.save_asset(
                asset_type="strategy",
                payload={"strategy_id": "fresh_for_cooldown_test"},
                actor_role="pm",
                group_key="2026-04-17",
            )
            monitor, dispatcher = _build_agent_wake_monitor(harness)
            monitor.scan_once(now=datetime(2026, 4, 17, 0, 55, tzinfo=UTC))
            monitor.scan_once(now=datetime(2026, 4, 17, 1, 2, tzinfo=UTC))
            # 5 min after first fire: still inside 30-min cooldown → no second send
            monitor.scan_once(now=datetime(2026, 4, 17, 1, 7, tzinfo=UTC))
            self.assertEqual(len(dispatcher.sends), 1)
        finally:
            harness.cleanup()

    def test_disabled_rule_does_not_fire(self) -> None:
        from openclaw_trader.modules.workflow_orchestrator.agent_wake import AgentWakeMonitor, AgentWakeSettings

        harness = build_test_harness()
        try:
            rule = _pm_wake_rule()
            rule = type(rule)(
                name=rule.name,
                agent=rule.agent,
                target_session_key=rule.target_session_key,
                message_source=rule.message_source,
                fire_when_any_of=rule.fire_when_any_of,
                cooldown_minutes=rule.cooldown_minutes,
                enabled=False,
                thinking=rule.thinking,
                turn_timeout_seconds=rule.turn_timeout_seconds,
            )
            dispatcher = FakeAgentDispatcher(payload_by_job={rule.message_source.job_id: "msg"})
            settings = AgentWakeSettings(enabled=True, scan_interval_seconds=60, rules=(rule,))
            monitor = AgentWakeMonitor(
                memory_assets=harness.container.memory_assets,
                dispatcher=dispatcher,
                settings=settings,
                event_bus=harness.event_bus,
            )
            monitor.scan_once(now=datetime(2026, 4, 17, 1, 2, tzinfo=UTC))
            self.assertEqual(len(dispatcher.sends), 0)
        finally:
            harness.cleanup()

    def test_missing_message_source_records_error_and_skips_send(self) -> None:
        harness = build_test_harness()
        try:
            # Dispatcher returns None for payload → rule should not send.
            from openclaw_trader.modules.workflow_orchestrator.agent_wake import AgentWakeMonitor, AgentWakeSettings

            rule = _pm_wake_rule()
            dispatcher = FakeAgentDispatcher(payload_by_job={})  # empty → None
            settings = AgentWakeSettings(enabled=True, scan_interval_seconds=60, rules=(rule,))
            monitor = AgentWakeMonitor(
                memory_assets=harness.container.memory_assets,
                dispatcher=dispatcher,
                settings=settings,
                event_bus=harness.event_bus,
            )
            # 13h silence makes max_silence_since fire
            result = monitor.scan_once(now=datetime.now(UTC) + timedelta(hours=24))
            self.assertEqual(len(dispatcher.sends), 0)
            self.assertEqual(result["fires"][0]["fired"], False)
            self.assertEqual(result["fires"][0]["error"], "missing_message_source")
        finally:
            harness.cleanup()

    def test_state_persisted_across_scans(self) -> None:
        harness = build_test_harness()
        try:
            harness.container.memory_assets.save_asset(
                asset_type="strategy",
                payload={"strategy_id": "fresh_for_state_test"},
                actor_role="pm",
                group_key="2026-04-17",
            )
            monitor, _ = _build_agent_wake_monitor(harness)
            monitor.scan_once(now=datetime(2026, 4, 17, 0, 55, tzinfo=UTC))
            monitor.scan_once(now=datetime(2026, 4, 17, 1, 2, tzinfo=UTC))
            state_asset = harness.container.memory_assets.get_asset("agent_wake_state")
            self.assertIsNotNone(state_asset)
            rules = state_asset["payload"]["rules"]
            self.assertIn("pm_main_heartbeat", rules)
            self.assertEqual(rules["pm_main_heartbeat"]["last_fire_predicate"], "cron_time")
            self.assertTrue(rules["pm_main_heartbeat"]["last_fire_ok"])
        finally:
            harness.cleanup()


if __name__ == "__main__":
    unittest.main()
