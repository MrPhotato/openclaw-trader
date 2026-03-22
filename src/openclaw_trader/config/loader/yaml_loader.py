from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text())
    return payload if isinstance(payload, dict) else {}


def normalized_forecast_horizons(payload: dict[str, Any]) -> dict[str, int]:
    defaults = {"1h": 4, "4h": 16, "12h": 48}
    raw = dict(payload.get("forecast_horizons") or {})
    if "forecast_horizon_bars" in payload:
        raw.setdefault("1h", payload["forecast_horizon_bars"])
    merged: dict[str, int] = {}
    for horizon, fallback in defaults.items():
        try:
            merged[horizon] = max(int(raw.get(horizon, fallback)), 1)
        except Exception:
            merged[horizon] = fallback
    return merged
