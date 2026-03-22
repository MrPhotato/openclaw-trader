from __future__ import annotations

from typing import Protocol

from .models import ManualTriggerCommand


class WorkflowCommandHandler(Protocol):
    def handle(self, command: ManualTriggerCommand, *, workflow_id: str, trace_id: str) -> dict: ...
