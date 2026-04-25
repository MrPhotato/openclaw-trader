from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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
        """Fan all upstream HTTP calls out in parallel.

        Brent / WTI / DXY / US10Y / each ETF / Fear-Greed are independent
        upstream queries with no ordering constraints. Running them serially
        meant the bridge tick spent (sum of HTTP latencies) per refresh; with
        the cadence dropped from 900s → 30s on 2026-04-25 that became a real
        bottleneck (bridge cycle stretched from ~37s to ~120s). Submitting
        them all to a small ThreadPoolExecutor cuts wall time to ~max latency
        instead of sum. yfinance / alternative.me providers expose the same
        `fetch_*` API so the surface stays unchanged; httpx.Client (used
        underneath) is documented thread-safe so a single shared client per
        provider is fine.
        """
        symbols = dict(self._config.symbols or DEFAULT_MACRO_SYMBOLS)
        quote_aliases: tuple[str, ...] = ("brent", "wti", "dxy", "us10y_yield_pct")
        etf_tickers: tuple[str, ...] = tuple(self._config.etf_tickers)

        def _fetch_quote(alias: str) -> MacroPrice:
            yahoo = symbols.get(alias) or ""
            if not yahoo or self._price is None:
                return MacroPrice(symbol=yahoo or alias, error="provider_disabled")
            return self._price.fetch_quote(yahoo)

        def _fetch_etf(ticker: str) -> EtfActivity:
            if self._price is None:
                return EtfActivity(ticker=ticker, error="provider_disabled")
            return self._price.fetch_etf_activity(ticker)

        def _fetch_fear_greed() -> FearGreedIndex:
            if self._sentiment is None:
                return FearGreedIndex(error="provider_disabled")
            return self._sentiment.fetch_btc_fear_greed()

        max_workers = max(1, len(quote_aliases) + len(etf_tickers) + 1)
        with ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="macro_data"
        ) as pool:
            quote_futures = {alias: pool.submit(_fetch_quote, alias) for alias in quote_aliases}
            etf_futures = {ticker: pool.submit(_fetch_etf, ticker) for ticker in etf_tickers}
            fg_future = pool.submit(_fetch_fear_greed)

        # Pool exits only after every submitted task completes — at this point
        # every future is `done()`, so .result() is non-blocking. Errors are
        # captured INSIDE each MacroPrice/EtfActivity/FearGreedIndex by the
        # provider (same contract as before), so no exceptions escape here.
        errors: list[str] = []
        quotes: dict[str, MacroPrice] = {}
        for alias, future in quote_futures.items():
            quote = future.result()
            quotes[alias] = quote
            if quote.error:
                errors.append(f"{alias}:{quote.error}")

        etf_activity: dict[str, EtfActivity] = {}
        for ticker, future in etf_futures.items():
            activity = future.result()
            etf_activity[ticker] = activity
            if activity.error:
                errors.append(f"etf:{ticker}:{activity.error}")

        fear_greed = fg_future.result()
        if fear_greed.error:
            errors.append(f"fear_greed:{fear_greed.error}")

        return MacroSnapshot(
            snapshot_id=new_id("macro_snapshot"),
            captured_at_utc=now,
            brent=quotes["brent"],
            wti=quotes["wti"],
            dxy=quotes["dxy"],
            us10y_yield_pct=quotes["us10y_yield_pct"],
            btc_fear_greed=fear_greed,
            btc_etf_activity=etf_activity,
            fetch_errors=errors,
        )

    def snapshot_as_dict(self, snapshot: MacroSnapshot | None) -> dict[str, Any]:
        if snapshot is None:
            return {}
        return snapshot.model_dump(mode="json")
