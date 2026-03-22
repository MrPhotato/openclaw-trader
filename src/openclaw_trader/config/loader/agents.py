from __future__ import annotations

import os
from typing import Any

from ..models import AgentSettings


def env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def build_agent_settings(payload: dict[str, Any] | None = None) -> AgentSettings:
    payload = dict(payload or {})
    return AgentSettings(
        openclaw_enabled=env_flag("OPENCLAW_V2_OPENCLAW_ENABLED", bool(payload.get("openclaw_enabled", False))),
        pm_agent=os.getenv("OPENCLAW_V2_PM_AGENT", str(payload.get("pm_agent", "pm"))),
        risk_trader_agent=os.getenv("OPENCLAW_V2_RISK_AGENT", str(payload.get("risk_trader_agent", "risk-trader"))),
        macro_event_analyst_agent=os.getenv(
            "OPENCLAW_V2_MACRO_AGENT",
            str(payload.get("macro_event_analyst_agent", "macro-event-analyst")),
        ),
        crypto_chief_agent=os.getenv("OPENCLAW_V2_CHIEF_AGENT", str(payload.get("crypto_chief_agent", "crypto-chief"))),
        openclaw_timeout_seconds=int(os.getenv("OPENCLAW_V2_OPENCLAW_TIMEOUT_SECONDS", str(payload.get("openclaw_timeout_seconds", 60)))),
    )
