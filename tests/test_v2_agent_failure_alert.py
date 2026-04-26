from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from openclaw_trader.modules.workflow_orchestrator.agent_failure_alert import (
    AgentFailureAlertConfig,
    AgentFailureAlertMonitor,
    _STATE_ASSET_ID,
)

from .helpers_v2 import build_test_harness


_QUOTA_ERROR_LINE = (
    "2026-04-26T14:32:15.123+08:00 [agent/embedded] embedded run agent end: "
    "runId=abc-123 isError=true model=gpt-5.4 provider=openai-codex "
    "error=⚠️ You have hit your ChatGPT usage limit (plus plan). "
    "Try again in ~5519 min."
)

_BAILIAN_QUOTA_LINE = (
    "2026-04-24T01:38:03.153+08:00 [agent/embedded] embedded run agent end: "
    "runId=def-456 isError=true model=qwen3.6-plus provider=bailian "
    "error=⚠️ month allocated quota exceeded."
)

_HEALTHY_LINE = (
    "2026-04-26T14:31:00.000+08:00 [agent/embedded] embedded run agent end: "
    "runId=ghi-789 isError=false model=gpt-5.4 provider=openai-codex"
)


def _write_log(tmpdir: Path, lines: list[str]) -> Path:
    log_path = tmpdir / "gateway.err.log"
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log_path


class AgentFailureAlertMonitorTests(unittest.TestCase):
    """Spec: monitor must (a) detect known fatal LLM failure patterns from
    gateway.err.log, (b) dispatch a single owner wecom alert per
    (provider, kind), (c) honor cooldown so a steady error stream does not
    spam the owner.
    """

    def test_dispatches_alert_on_first_quota_failure(self) -> None:
        harness = build_test_harness()
        with tempfile.TemporaryDirectory() as raw_dir:
            tmpdir = Path(raw_dir)
            log_path = _write_log(tmpdir, [_HEALTHY_LINE, _QUOTA_ERROR_LINE])
            try:
                monitor = AgentFailureAlertMonitor(
                    memory_assets=harness.container.memory_assets,
                    notification_service=harness.container.notification_service,
                    config=AgentFailureAlertConfig(
                        enabled=True,
                        log_path=str(log_path),
                        cooldown_minutes=60,
                    ),
                )
                result = monitor.scan_once()
                self.assertEqual(result["new_failures"], 1)
                self.assertEqual(result["alerts_dispatched"], ["openai-codex:openai_oauth_weekly_limit"])
                # And the wecom command actually went through the fake notifier
                cmds = harness.fake_notifier.commands
                self.assertEqual(len(cmds), 1)
                self.assertIn("ChatGPT Plus 周限额触顶", cmds[0].message)
                self.assertIn("openai-codex/gpt-5.4", cmds[0].message)
                self.assertTrue(cmds[0].message_type.startswith("agent_llm_failure:"))
            finally:
                harness.cleanup()

    def test_cooldown_suppresses_repeated_alert(self) -> None:
        harness = build_test_harness()
        with tempfile.TemporaryDirectory() as raw_dir:
            tmpdir = Path(raw_dir)
            log_path = _write_log(tmpdir, [_QUOTA_ERROR_LINE])
            try:
                monitor = AgentFailureAlertMonitor(
                    memory_assets=harness.container.memory_assets,
                    notification_service=harness.container.notification_service,
                    config=AgentFailureAlertConfig(
                        enabled=True,
                        log_path=str(log_path),
                        cooldown_minutes=60,
                    ),
                )
                first_now = datetime(2026, 4, 26, 14, 33, tzinfo=UTC)
                monitor.scan_once(now=first_now)
                self.assertEqual(len(harness.fake_notifier.commands), 1)
                # Append another identical failure 5 min later — within cooldown
                later_line = _QUOTA_ERROR_LINE.replace(
                    "2026-04-26T14:32:15.123+08:00", "2026-04-26T14:38:00.000+08:00"
                )
                with log_path.open("a", encoding="utf-8") as fh:
                    fh.write(later_line + "\n")
                monitor.scan_once(now=first_now + timedelta(minutes=5))
                self.assertEqual(
                    len(harness.fake_notifier.commands),
                    1,
                    "Within 60min cooldown the second occurrence must NOT fire a new alert",
                )
            finally:
                harness.cleanup()

    def test_separate_provider_alerts_independently(self) -> None:
        """Bailian quota and OpenAI quota are independent failure surfaces;
        each gets its own alert even if they overlap in time.
        """
        harness = build_test_harness()
        with tempfile.TemporaryDirectory() as raw_dir:
            tmpdir = Path(raw_dir)
            log_path = _write_log(tmpdir, [_QUOTA_ERROR_LINE, _BAILIAN_QUOTA_LINE])
            try:
                monitor = AgentFailureAlertMonitor(
                    memory_assets=harness.container.memory_assets,
                    notification_service=harness.container.notification_service,
                    config=AgentFailureAlertConfig(
                        enabled=True, log_path=str(log_path), cooldown_minutes=60
                    ),
                )
                result = monitor.scan_once()
                dispatched = sorted(result["alerts_dispatched"])
                self.assertEqual(
                    dispatched,
                    ["bailian:bailian_month_quota", "openai-codex:openai_oauth_weekly_limit"],
                )
                self.assertEqual(len(harness.fake_notifier.commands), 2)
            finally:
                harness.cleanup()

    def test_healthy_log_produces_no_alert(self) -> None:
        harness = build_test_harness()
        with tempfile.TemporaryDirectory() as raw_dir:
            tmpdir = Path(raw_dir)
            log_path = _write_log(tmpdir, [_HEALTHY_LINE])
            try:
                monitor = AgentFailureAlertMonitor(
                    memory_assets=harness.container.memory_assets,
                    notification_service=harness.container.notification_service,
                    config=AgentFailureAlertConfig(enabled=True, log_path=str(log_path)),
                )
                result = monitor.scan_once()
                self.assertEqual(result["new_failures"], 0)
                self.assertEqual(harness.fake_notifier.commands, [])
            finally:
                harness.cleanup()

    def test_skips_lines_without_provider_tag(self) -> None:
        """[compaction] summarization failures piggyback the same error
        string but are NOT the primary agent-end event. The primary
        [agent/embedded] line will carry provider= and is what we alert on.
        """
        compaction_line = (
            "2026-04-26T14:20:01.000+08:00 [compaction] Full summarization "
            "failed: Summarization failed: You have hit your ChatGPT usage "
            "limit (plus plan). Try again in ~93 min."
        )
        harness = build_test_harness()
        with tempfile.TemporaryDirectory() as raw_dir:
            tmpdir = Path(raw_dir)
            log_path = _write_log(tmpdir, [compaction_line])
            try:
                monitor = AgentFailureAlertMonitor(
                    memory_assets=harness.container.memory_assets,
                    notification_service=harness.container.notification_service,
                    config=AgentFailureAlertConfig(enabled=True, log_path=str(log_path)),
                )
                result = monitor.scan_once()
                self.assertEqual(result["new_failures"], 0)
                self.assertEqual(harness.fake_notifier.commands, [])
            finally:
                harness.cleanup()

    def test_state_persists_across_scans(self) -> None:
        """`last_scanned_at_utc` must be saved so a second scan starts from
        the previous high-water mark and doesn't re-emit old failures.
        """
        harness = build_test_harness()
        with tempfile.TemporaryDirectory() as raw_dir:
            tmpdir = Path(raw_dir)
            log_path = _write_log(tmpdir, [_QUOTA_ERROR_LINE])
            try:
                monitor = AgentFailureAlertMonitor(
                    memory_assets=harness.container.memory_assets,
                    notification_service=harness.container.notification_service,
                    config=AgentFailureAlertConfig(
                        enabled=True, log_path=str(log_path), cooldown_minutes=60
                    ),
                )
                monitor.scan_once()
                state_asset = harness.container.memory_assets.get_asset(_STATE_ASSET_ID)
                self.assertIsNotNone(state_asset)
                payload = state_asset.get("payload") or {}
                self.assertIsNotNone(payload.get("last_scanned_at_utc"))
                self.assertIn(
                    "openai-codex:openai_oauth_weekly_limit", (payload.get("last_alerts") or {})
                )
            finally:
                harness.cleanup()


if __name__ == "__main__":
    unittest.main()
