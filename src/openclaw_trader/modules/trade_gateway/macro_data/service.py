from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from ....shared.utils import new_id
from .models import EtfActivity, FearGreedIndex, MacroPrice, MacroSnapshot
from .ports import MacroDataProvider, SentimentProvider


DEFAULT_MACRO_SYMBOLS: dict[str, str] = {
    "brent": "BZ=F",
    "wti": "CL=F",
    "dxy": "DX-Y.NYB",
    "us10y_yield_pct": "^TNX",
}

DEFAULT_ETF_TICKERS: tuple[str, ...] = ("IBIT", "FBTC", "ARKB")


@dataclass(frozen=True)
class MacroDataConfig:
    enabled: bool = False
    refresh_interval_seconds: int = 900
    symbols: dict[str, str] | None = None
    etf_tickers: tuple[str, ...] = DEFAULT_ETF_TICKERS


class MacroDataService:
    def __init__(
        self,
        *,
        price_provider: MacroDataProvider | None,
        sentiment_provider: SentimentProvider | None,
        config: MacroDataConfig | None = None,
    ) -> None:
        self._price = price_provider
        self._sentiment = sentiment_provider
        self._config = config or MacroDataConfig()
        self._lock = Lock()
        self._latest: MacroSnapshot | None = None
        self._fetched_at: datetime | None = None

    @property
    def config(self) -> MacroDataConfig:
        return self._config

    def collect_snapshot(self, *, force_refresh: bool = False) -> MacroSnapshot | None:
        if not self._config.enabled:
            return None
        now = datetime.now(UTC)
        with self._lock:
            cached = self._latest
            fetched_at = self._fetched_at
        if (
            not force_refresh
            and cached is not None
            and fetched_at is not None
            and (now - fetched_at).total_seconds() < max(int(self._config.refresh_interval_seconds), 1)
        ):
            return cached
        snapshot = self._fetch_snapshot(now=now)
        with self._lock:
            self._latest = snapshot
            self._fetched_at = now
        return snapshot

    def latest(self) -> MacroSnapshot | None:
        with self._lock:
            return self._latest

    def _fetch_snapshot(self, *, now: datetime) -> MacroSnapshot:
        symbols = dict(self._config.symbols or DEFAULT_MACRO_SYMBOLS)
        errors: list[str] = []

        def _safe_quote(alias: str) -> MacroPrice:
            yahoo = symbols.get(alias) or ""
            if not yahoo or self._price is None:
                return MacroPrice(symbol=yahoo or alias, error="provider_disabled")
            quote = self._price.fetch_quote(yahoo)
            if quote.error:
                errors.append(f"{alias}:{quote.error}")
            return quote

        brent = _safe_quote("brent")
        wti = _safe_quote("wti")
        dxy = _safe_quote("dxy")
        us10y = _safe_quote("us10y_yield_pct")

        etf_activity: dict[str, EtfActivity] = {}
        for ticker in self._config.etf_tickers:
            if self._price is None:
                etf_activity[ticker] = EtfActivity(ticker=ticker, error="provider_disabled")
                continue
            result = self._price.fetch_etf_activity(ticker)
            etf_activity[ticker] = result
            if result.error:
                errors.append(f"etf:{ticker}:{result.error}")

        if self._sentiment is not None:
            fear_greed = self._sentiment.fetch_btc_fear_greed()
            if fear_greed.error:
                errors.append(f"fear_greed:{fear_greed.error}")
        else:
            fear_greed = FearGreedIndex(error="provider_disabled")
            errors.append("fear_greed:provider_disabled")

        return MacroSnapshot(
            snapshot_id=new_id("macro_snapshot"),
            captured_at_utc=now,
            brent=brent,
            wti=wti,
            dxy=dxy,
            us10y_yield_pct=us10y,
            btc_fear_greed=fear_greed,
            btc_etf_activity=etf_activity,
            fetch_errors=errors,
        )

    def snapshot_as_dict(self, snapshot: MacroSnapshot | None) -> dict[str, Any]:
        if snapshot is None:
            return {}
        return snapshot.model_dump(mode="json")
