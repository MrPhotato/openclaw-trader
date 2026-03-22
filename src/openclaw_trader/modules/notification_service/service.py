from __future__ import annotations

from collections.abc import Iterable

from ...shared.protocols import EventEnvelope, EventFactory
from ...config.loader import load_system_settings
from ...shared.utils import new_id
from ..state_memory.models import NotificationResult as StoredNotificationResult
from ..state_memory.service import StateMemoryService
from .events import EVENT_NOTIFICATION_SENT, MODULE_NAME
from .models import NotificationCommand
from .ports import NotificationProvider


class NotificationService:
    def __init__(self, provider: NotificationProvider, state_memory: StateMemoryService) -> None:
        self.provider = provider
        self.state_memory = state_memory
        self.settings = load_system_settings()

    def build_workflow_notifications(self, *, trace_id: str, strategy: dict, execution_results: list[dict]) -> list[NotificationCommand]:
        message = self._format_workflow_message(
            trace_id=trace_id,
            strategy=strategy,
            execution_results=execution_results,
        )
        return self._build_recipient_commands(
            message_type="workflow_summary",
            message=message,
            payload={
                "trace_id": trace_id,
                "strategy": strategy,
                "execution_results": execution_results,
            },
            include_owner=True,
            include_chief=True,
        )

    def send(self, command: NotificationCommand):
        result = self.provider.send(command)
        self.state_memory.save_notification_result(
            result=StoredNotificationResult(
                notification_id=result.notification_id,
                delivered=result.delivered,
                provider_message_id=result.provider_message_id,
                failure_reason=result.failure_reason,
                delivered_at=result.delivered_at,
            ),
            payload={"trace_id": command.payload.get("trace_id"), **command.model_dump(mode="json")},
        )
        return result

    def notify_owner_summary(self, *, trace_id: str, owner_summary: str) -> list[EventEnvelope]:
        commands = self._build_recipient_commands(
            message_type="chief_owner_summary",
            message="\n".join(["OpenClaw Chief Retro", owner_summary.strip()]),
            payload={"trace_id": trace_id, "owner_summary": owner_summary.strip()},
            include_owner=True,
            include_chief=False,
        )
        return self._send_commands(trace_id=trace_id, commands=commands)

    def handle_event(self, envelope: EventEnvelope) -> list[EventEnvelope]:
        if envelope.event_type != "strategy.submitted":
            return []
        payload = envelope.payload.get("strategy") if isinstance(envelope.payload.get("strategy"), dict) else envelope.payload
        commands = self._build_event_commands(
            trace_id=envelope.trace_id,
            message_type="strategy_update",
            strategy=payload if isinstance(payload, dict) else {},
            execution_results=[],
        )
        return self._send_commands(trace_id=envelope.trace_id, commands=commands)

    def _build_event_commands(
        self,
        *,
        trace_id: str,
        message_type: str,
        strategy: dict,
        execution_results: list[dict],
    ) -> list[NotificationCommand]:
        return self._build_recipient_commands(
            message_type=message_type,
            message=self._format_workflow_message(
                trace_id=trace_id,
                strategy=strategy,
                execution_results=execution_results,
            ),
            payload={
                "trace_id": trace_id,
                "strategy": strategy,
                "execution_results": execution_results,
            },
        )

    def _send_commands(self, *, trace_id: str, commands: Iterable[NotificationCommand]) -> list[EventEnvelope]:
        events: list[EventEnvelope] = []
        for command in commands:
            result = self.send(command)
            events.append(
                EventFactory.build(
                    trace_id=trace_id,
                    event_type=EVENT_NOTIFICATION_SENT,
                    source_module=MODULE_NAME,
                    entity_type="notification",
                    entity_id=result.notification_id,
                    payload={
                        "notification_id": result.notification_id,
                        "message_type": command.message_type,
                        "recipient": command.recipient,
                        "delivered": result.delivered,
                        "provider_message_id": result.provider_message_id,
                    },
                )
            )
        return events

    def _build_recipient_commands(
        self,
        *,
        message_type: str,
        message: str,
        payload: dict,
        include_owner: bool = True,
        include_chief: bool = True,
    ) -> list[NotificationCommand]:
        commands: list[NotificationCommand] = []
        if include_owner:
            commands.append(
                NotificationCommand(
                    notification_id=new_id("notification"),
                    channel=self.settings.notification.default_channel,
                    recipient=self.settings.notification.default_recipient,
                    account_id=self.settings.workflow.owner_account_id,
                    message_type=message_type,
                    message=message,
                    payload=payload,
                )
            )
        chief_recipient = self.settings.notification.chief_recipient or f"agent:{self.settings.agents.crypto_chief_agent}"
        if include_chief and chief_recipient != self.settings.notification.default_recipient:
            commands.append(
                NotificationCommand(
                    notification_id=new_id("notification"),
                    channel=self.settings.notification.default_channel,
                    recipient=chief_recipient,
                    message_type=message_type,
                    message=message,
                    payload=payload,
                )
            )
        return commands

    @staticmethod
    def _format_workflow_message(*, trace_id: str, strategy: dict, execution_results: list[dict]) -> str:
        lines = [
            "OpenClaw Trader v2",
            f"trace_id: {trace_id}",
        ]
        strategy_version = strategy.get("strategy_version") or strategy.get("strategy_id") or strategy.get("version")
        if strategy_version:
            lines.append(f"strategy: {strategy_version}")
        thesis = str(strategy.get("thesis") or strategy.get("portfolio_thesis") or "").strip()
        if thesis:
            lines.append(f"thesis: {thesis}")
        targets = strategy.get("targets") if isinstance(strategy.get("targets"), list) else []
        if targets:
            lines.append("targets:")
            for item in targets[:5]:
                if not isinstance(item, dict):
                    continue
                coin = item.get("coin") or item.get("symbol") or "UNKNOWN"
                bias = item.get("bias") or item.get("direction") or "neutral"
                share = item.get("target_position_share_pct")
                if share is None:
                    band = item.get("target_exposure_band_pct") or []
                    share = band[1] if len(band) > 1 else band[0] if band else 0
                lines.append(f"- {coin}: {bias} {share}%")
        if execution_results:
            lines.append(f"executions: {len(execution_results)}")
            for item in execution_results[:5]:
                if not isinstance(item, dict):
                    continue
                plan_id = item.get("plan_id") or "-"
                success = item.get("success")
                order_id = item.get("exchange_order_id") or "-"
                lines.append(f"- {plan_id}: success={success} order={order_id}")
        else:
            lines.append("executions: 0")
        return "\n".join(lines)
