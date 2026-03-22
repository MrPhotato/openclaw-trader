from __future__ import annotations

from typing import Protocol

from .models import NotificationCommand, NotificationResult


class NotificationProvider(Protocol):
    def send(self, command: NotificationCommand) -> NotificationResult: ...
