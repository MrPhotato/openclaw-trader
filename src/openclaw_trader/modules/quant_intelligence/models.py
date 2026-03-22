from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class HorizonSignal(BaseModel):
    horizon: str
    side: str
    confidence: float
    raw_probabilities: dict[str, float] = Field(default_factory=dict)
    calibrated_probabilities: dict[str, float] = Field(default_factory=dict)
    abstain_state: str = "accepted"
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class CoinForecast(BaseModel):
    coin: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    horizons: dict[str, HorizonSignal] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
