from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from openclaw_trader.modules.notification_service import NotificationService
from openclaw_trader.modules.notification_service.adapters.openclaw import OpenClawNotificationProvider
from openclaw_trader.modules.notification_service.models import NotificationCommand
from openclaw_trader.modules.state_memory import StateMemoryRepository, StateMemoryService
from openclaw_trader.shared.protocols import EventFactory
from openclaw_trader.shared.infra import SqliteDatabase

from .helpers_v2 import FakeNotificationProvider, TemporaryDirectory


class NotificationServiceTests(unittest.TestCase):
    def test_send_records_notification(self) -> None:
        tempdir = TemporaryDirectory()
        try:
            state_memory = StateMemoryService(StateMemoryRepository(SqliteDatabase(__import__("pathlib").Path(tempdir.name) / "db.sqlite")))
            notifier = FakeNotificationProvider()
            service = NotificationService(notifier, state_memory)
            commands = service.build_workflow_notifications(trace_id="trace-1", strategy={"version": "v1"}, execution_results=[])
            self.assertEqual(len(commands), 2)
            self.assertIn("trace_id: trace-1", commands[0].message)
            for command in commands:
                result = service.send(command)
                self.assertTrue(result.delivered)
            self.assertEqual(len(notifier.commands), 2)
            self.assertEqual(len(state_memory.query_events()), 2)
        finally:
            tempdir.cleanup()

    def test_notify_owner_summary_targets_owner_only(self) -> None:
        tempdir = TemporaryDirectory()
        try:
            state_memory = StateMemoryService(StateMemoryRepository(SqliteDatabase(__import__("pathlib").Path(tempdir.name) / "db.sqlite")))
            notifier = FakeNotificationProvider()
            service = NotificationService(notifier, state_memory)

            events = service.notify_owner_summary(trace_id="trace-chief", owner_summary="Retro summary ready.")

            self.assertEqual(len(events), 1)
            self.assertEqual(len(notifier.commands), 1)
            command = notifier.commands[0]
            self.assertEqual(command.message_type, "chief_owner_summary")
            self.assertEqual(command.recipient, service.settings.notification.default_recipient)
            self.assertNotIn("agent:crypto-chief", [item.recipient for item in notifier.commands])
        finally:
            tempdir.cleanup()

    def test_handle_event_ignores_execution_completed(self) -> None:
        tempdir = TemporaryDirectory()
        try:
            state_memory = StateMemoryService(StateMemoryRepository(SqliteDatabase(__import__("pathlib").Path(tempdir.name) / "db.sqlite")))
            notifier = FakeNotificationProvider()
            service = NotificationService(notifier, state_memory)

            envelope = EventFactory.build(
                trace_id="trace-exec",
                event_type="execution.result.completed",
                source_module="execution_gateway",
                entity_type="execution_result",
                entity_id="result-1",
                payload={"plan_id": "plan-1", "success": True},
            )

            events = service.handle_event(envelope)

            self.assertEqual(events, [])
            self.assertEqual(notifier.commands, [])
        finally:
            tempdir.cleanup()


class OpenClawNotificationProviderTests(unittest.TestCase):
    @patch("openclaw_trader.modules.notification_service.adapters.openclaw.subprocess.run")
    def test_agent_recipient_uses_chat_inject(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"version":"unknown"} noise\n{"ok":true,"messageId":"msg-chief-1"}',
            stderr="",
        )
        provider = OpenClawNotificationProvider()

        result = provider.send(
            NotificationCommand(
                notification_id="notif-1",
                channel="wecom-app",
                recipient="agent:crypto-chief",
                message_type="strategy_update",
                message="chief note",
                payload={},
            )
        )

        self.assertTrue(result.delivered)
        self.assertEqual(result.provider_message_id, "msg-chief-1")
        cmd = run_mock.call_args.args[0]
        self.assertEqual(cmd[:4], ["openclaw", "gateway", "call", "chat.inject"])
        self.assertIn("agent:crypto-chief:main", " ".join(cmd))

    @patch("openclaw_trader.modules.notification_service.adapters.openclaw.subprocess.run")
    def test_external_recipient_passes_channel(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"messageId":"msg-user-1"}',
            stderr="",
        )
        provider = OpenClawNotificationProvider()

        result = provider.send(
            NotificationCommand(
                notification_id="notif-2",
                channel="wecom-app",
                recipient="user:owner",
                account_id="default",
                message_type="strategy_update",
                message="owner note",
                payload={},
            )
        )

        self.assertTrue(result.delivered)
        cmd = run_mock.call_args.args[0]
        self.assertIn("--channel", cmd)
        self.assertIn("wecom-app", cmd)


if __name__ == "__main__":
    unittest.main()
