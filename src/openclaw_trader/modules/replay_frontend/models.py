from __future__ import annotations

from pydantic import BaseModel


class ReplayQuery(BaseModel):
    trace_id: str | None = None
    module: str | None = None
