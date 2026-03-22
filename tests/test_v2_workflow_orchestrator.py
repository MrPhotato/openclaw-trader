from __future__ import annotations

import unittest

from openclaw_trader.modules.workflow_orchestrator.models import ManualTriggerCommand

from .helpers_v2 import build_test_harness


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

    def test_path_4_chief_retro_emits_summary_without_resetting_sessions(self) -> None:
        harness = build_test_harness(news_severity="high")
        try:
            harness.container.state_memory.materialize_strategy_asset(
                trace_id="trace-seed-strategy",
                authored_payload={
                    "portfolio_mode": "defensive",
                    "target_gross_exposure_band_pct": [5.0, 15.0],
                    "portfolio_thesis": "Seed strategy for retro.",
                    "portfolio_invalidation": "Seed invalidation.",
                    "change_summary": "Seeded before retro.",
                    "targets": [],
                    "scheduled_rechecks": [],
                },
                trigger_type="manual",
            )
            receipt = harness.container.workflow_orchestrator.submit_command(
                ManualTriggerCommand(command_id="cmd-chief", command_type="run_chief_retro", initiator="test")
            )
            self.assertTrue(receipt.accepted)
            workflow = harness.wait_for_workflow(receipt.trace_id)
            self.assertEqual(workflow.state, "completed")
            projection_assets = harness.container.state_memory.recent_assets(asset_type="memory_projection", limit=10)
            self.assertIsNone(harness.container.state_memory.latest_asset(asset_type="chief_retro"))
            self.assertEqual(len(projection_assets), 0)
            self.assertEqual(len(harness.fake_session_controller.resets), 0)
            agent_sessions = harness.container.state_memory.list_agent_sessions()
            self.assertEqual(
                {session["agent_role"] for session in agent_sessions},
                {"crypto_chief"},
            )
            transcript_events = harness.container.state_memory.query_events(
                trace_id=receipt.trace_id,
                module="agent_gateway",
                limit=50,
            )
            completed_events = [item for item in transcript_events if item["event_type"] == "chief.retro.completed"]
            self.assertEqual(len(completed_events), 1)
            retro_payload = completed_events[0]["payload"]
            self.assertEqual(retro_payload["round_count"], 2)
            self.assertEqual(len(retro_payload["transcript"]), 8)
            self.assertEqual(
                {item["speaker_role"] for item in retro_payload["transcript"]},
                {"pm", "risk_trader", "macro_event_analyst", "crypto_chief"},
            )
            owner_summary_notifications = [
                command for command in harness.fake_notifier.commands if command.message_type == "chief_owner_summary"
            ]
            self.assertEqual(len(owner_summary_notifications), 1)
            self.assertEqual(
                owner_summary_notifications[0].recipient,
                harness.container.notification_service.settings.notification.default_recipient,
            )
            self.assertNotIn(
                "agent:crypto-chief",
                [command.recipient for command in harness.fake_notifier.commands if command.message_type == "chief_owner_summary"],
            )
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
            agent_sessions = harness.container.state_memory.list_agent_sessions()
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
                for session in harness.container.state_memory.list_agent_sessions()
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
            self.assertIsNone(harness.container.state_memory.get_workflow_by_command("cmd-invalid-pm"))
        finally:
            harness.cleanup()


if __name__ == "__main__":
    unittest.main()
