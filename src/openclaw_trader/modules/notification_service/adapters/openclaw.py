from __future__ import annotations

import json
import subprocess
from json import JSONDecodeError, JSONDecoder
from typing import Any

from ....config.loader import load_system_settings
from ...notification_service.models import NotificationCommand, NotificationResult


class OpenClawNotificationProvider:
    def __init__(self) -> None:
        self.settings = load_system_settings()

    def send(self, command: NotificationCommand) -> NotificationResult:
        if command.recipient.startswith("agent:"):
            return self._inject_agent_session_note(command)

        cmd = [
            "openclaw",
            "message",
            "send",
            "--channel",
            command.channel,
            "--target",
            command.recipient,
            "--message",
            command.message,
            "--json",
        ]
        if command.account_id:
            cmd.extend(["--account", command.account_id])
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        payload = self._parse_json(completed.stdout)
        if completed.returncode == 0:
            provider_message_id = str(
                payload.get("messageId")
                or payload.get("message_id")
                or payload.get("id")
                or command.notification_id
            )
            return NotificationResult(
                notification_id=command.notification_id,
                delivered=True,
            provider_message_id=provider_message_id,
        )
        return NotificationResult(
            notification_id=command.notification_id,
            delivered=False,
            failure_reason=completed.stderr.strip() or completed.stdout.strip() or "openclaw_message_send_failed",
        )

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        value = _extract_last_json_value(text)
        return value if isinstance(value, dict) else {}

    def _inject_agent_session_note(self, command: NotificationCommand) -> NotificationResult:
        session_key = _session_key_for_recipient(command.recipient)
        cmd = [
            "openclaw",
            "gateway",
            "call",
            "chat.inject",
            "--json",
            "--params",
            json.dumps(
                {
                    "sessionKey": session_key,
                    "message": command.message,
                    "label": command.message_type,
                },
                ensure_ascii=False,
            ),
        ]
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        payload = self._parse_json(completed.stdout)
        if completed.returncode == 0 and bool(payload.get("ok")):
            provider_message_id = str(payload.get("messageId") or command.notification_id)
            return NotificationResult(
                notification_id=command.notification_id,
                delivered=True,
                provider_message_id=provider_message_id,
            )
        return NotificationResult(
            notification_id=command.notification_id,
            delivered=False,
            failure_reason=completed.stderr.strip() or completed.stdout.strip() or "openclaw_chat_inject_failed",
        )


def _session_key_for_recipient(recipient: str) -> str:
    if recipient.count(":") >= 2:
        return recipient
    agent_id = recipient.split(":", 1)[1] if ":" in recipient else recipient
    return f"agent:{agent_id}:main"


def _extract_last_json_value(text: str) -> Any | None:
    stripped = text.strip()
    if not stripped:
        return None
    decoder = JSONDecoder()
    values: list[Any] = []
    index = 0
    while index < len(stripped):
        char = stripped[index]
        if char not in "{[":
            index += 1
            continue
        try:
            value, end = decoder.raw_decode(stripped, index)
        except JSONDecodeError:
            index += 1
            continue
        values.append(value)
        index = end
    return values[-1] if values else None
