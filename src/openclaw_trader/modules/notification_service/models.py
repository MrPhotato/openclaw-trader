from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class NotificationCommand(BaseModel):
    notification_id: str
    channel: str
    recipient: str
    account_id: str | None = None
    message_type: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)


class NotificationResult(BaseModel):
    notification_id: str
    delivered: bool
    provider_message_id: str | None = None
    failure_reason: str | None = None
    delivered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
