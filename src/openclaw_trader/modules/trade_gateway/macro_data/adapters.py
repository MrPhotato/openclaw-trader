from __future__ import annotations

import ssl
from datetime import UTC, datetime
from typing import Any

import certifi
import httpx

from .models import EtfActivity, FearGreedIndex, MacroPrice


YFINANCE_CHART_URL = "https://query1.finance.yahoo.com/v7/finance/chart/{symbol}"
ALTERNATIVE_ME_FNG_URL = "https://api.alternative.me/fng/"

DEFAULT_USER_AGENT = "Mozilla/5.0"


def _build_client(timeout: float) -> httpx.Client:
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    return httpx.Client(
        timeout=timeout,
        verify=ssl_context,
        trust_env=False,
        headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"},
    )


def _epoch_to_utc(ts: Any) -> datetime | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=UTC)
    except (TypeError, ValueError):
        return None


class YFinanceMacroProvider:
    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        self._timeout = float(timeout_seconds)
        self._client = _build_client(self._timeout)

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    def __del__(self) -> None:  # pragma: no cover
        self.close()

    def fetch_quote(self, yahoo_symbol: str) -> MacroPrice:
        url = YFINANCE_CHART_URL.format(symbol=yahoo_symbol)
        try:
            resp = self._client.get(url, params={"interval": "15m", "range": "1d"})
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            return MacroPrice(symbol=yahoo_symbol, error=f"yfinance_fetch_failed:{type(exc).__name__}")
        meta = (
            ((data or {}).get("chart") or {}).get("result") or [{}]
        )[0].get("meta") or {}
        price = meta.get("regularMarketPrice")
        ts = _epoch_to_utc(meta.get("regularMarketTime"))
        now = datetime.now(UTC)
        staleness = int((now - ts).total_seconds()) if ts is not None else None
        # Yahoo market state values: REGULAR / CLOSED / PRE / POST / PREPRE / POSTPOST
        market_state = str(meta.get("marketState") or "").upper()
        is_open = market_state == "REGULAR"
        return MacroPrice(
            symbol=yahoo_symbol,
            price=float(price) if price is not None else None,
            as_of_utc=ts,
            is_market_open=is_open,
            staleness_seconds=staleness,
            source="yfinance",
        )

    def fetch_etf_activity(self, ticker: str) -> EtfActivity:
        url = YFINANCE_CHART_URL.format(symbol=ticker)
        try:
            resp = self._client.get(url, params={"interval": "1d", "range": "1mo"})
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            return EtfActivity(ticker=ticker, error=f"yfinance_fetch_failed:{type(exc).__name__}")
        result = (((data or {}).get("chart") or {}).get("result") or [{}])[0]
        meta = result.get("meta") or {}
        timestamps = list(result.get("timestamp") or [])
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        closes = list(quote.get("close") or [])
        volumes = list(quote.get("volume") or [])
        if not timestamps or not closes or not volumes:
            return EtfActivity(ticker=ticker, error="yfinance_empty_series")
        last_close = closes[-1] if closes[-1] is not None else meta.get("regularMarketPrice")
        last_volume = volumes[-1]
        tail_volumes = [v for v in volumes[-20:] if isinstance(v, (int, float))]
        avg_vol_20d = (sum(tail_volumes) / len(tail_volumes)) if tail_volumes else None
        ts = _epoch_to_utc(timestamps[-1])
        return EtfActivity(
            ticker=ticker,
            close=float(last_close) if last_close is not None else None,
            volume=int(last_volume) if last_volume is not None else None,
            avg_volume_20d=float(avg_vol_20d) if avg_vol_20d is not None else None,
            as_of_utc=ts,
            source="yfinance",
        )


class AlternativeMeFearGreedProvider:
    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        self._timeout = float(timeout_seconds)
        self._client = _build_client(self._timeout)

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    def __del__(self) -> None:  # pragma: no cover
        self.close()

    def fetch_btc_fear_greed(self) -> FearGreedIndex:
        try:
            resp = self._client.get(ALTERNATIVE_ME_FNG_URL, params={"limit": 1})
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            return FearGreedIndex(error=f"alternative_me_fetch_failed:{type(exc).__name__}")
        entries = list((data or {}).get("data") or [])
        if not entries:
            return FearGreedIndex(error="alternative_me_empty")
        entry = entries[0]
        try:
            value = int(entry.get("value"))
        except (TypeError, ValueError):
            value = None
        return FearGreedIndex(
            value=value,
            classification=str(entry.get("value_classification") or "") or None,
            as_of_utc=_epoch_to_utc(entry.get("timestamp")),
            source="alternative.me",
        )
