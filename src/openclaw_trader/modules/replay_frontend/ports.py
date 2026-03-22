from __future__ import annotations

from typing import Protocol

from ..state_memory.models import ReplayQueryView


class ReplayReadPort(Protocol):
    def query_replay(self, *, trace_id: str | None = None, module: str | None = None) -> ReplayQueryView: ...
