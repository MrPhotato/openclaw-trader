from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np

from ....config.models import QuantSettings
from ....shared.integrations.coinbase import CoinbaseAdvancedClient
from ....shared.protocols import Candle


MAX_PUBLIC_CANDLES_PER_REQUEST = 300
GRANULARITY_BY_INTERVAL = {
    "1m": ("ONE_MINUTE", 60),
    "5m": ("FIVE_MINUTE", 300),
    "15m": ("FIFTEEN_MINUTE", 900),
    "30m": ("THIRTY_MINUTE", 1800),
    "1h": ("ONE_HOUR", 3600),
    "2h": ("TWO_HOUR", 7200),
    "6h": ("SIX_HOUR", 21600),
    "1d": ("ONE_DAY", 86400),
}


def _cache_file(cache_dir: Path, *, coin: str, interval: str) -> Path:
    return cache_dir / f"{coin.upper()}_{interval}.joblib"


def _load_cached_candles(cache_dir: Path, *, coin: str, interval: str) -> dict[int, Candle]:
    path = _cache_file(cache_dir, coin=coin, interval=interval)
    if not path.exists():
        return {}
    try:
        payload = joblib.load(path)
    except Exception:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        return {}
    if not isinstance(payload, dict):
        return {}
    candles: dict[int, Candle] = {}
    for raw_start, raw_payload in payload.items():
        try:
            candle = raw_payload if isinstance(raw_payload, Candle) else Candle(**raw_payload)
            candles[int(raw_start)] = candle
        except Exception:
            continue
    return candles


def _save_cached_candles(cache_dir: Path, *, coin: str, interval: str, candles: dict[int, Candle]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {int(start): candle.model_dump(mode="json") for start, candle in candles.items()}
    joblib.dump(payload, _cache_file(cache_dir, coin=coin, interval=interval))


def fetch_candles(
    client: CoinbaseAdvancedClient,
    *,
    coin: str,
    quant: QuantSettings,
    lookback_bars: int | None = None,
    cache_dir: Path | None = None,
    now: datetime | None = None,
) -> list[Candle]:
    granularity, interval_seconds = GRANULARITY_BY_INTERVAL.get(quant.interval, ("FIFTEEN_MINUTE", 900))
    lookback = max(int(lookback_bars or quant.history_bars), 1)
    end = int((now or datetime.now(UTC)).astimezone(UTC).timestamp())
    required_start = end - (lookback * interval_seconds)
    product_id = f"{coin.upper()}-PERP-INTX"
    candles_by_start: dict[int, Candle] = (
        _load_cached_candles(cache_dir, coin=coin, interval=quant.interval) if cache_dir is not None else {}
    )

    if not candles_by_start:
        window_end = end
        remaining = lookback
    else:
        earliest_cached = min(candles_by_start)
        latest_cached = max(candles_by_start)
        window_end = min(required_start, earliest_cached)
        remaining = max(int(np.ceil((max(earliest_cached - required_start, 0)) / interval_seconds)), 0)
        if latest_cached < end:
            forward_cursor = latest_cached + interval_seconds
            while forward_cursor < end:
                batch_end = min(end, forward_cursor + (MAX_PUBLIC_CANDLES_PER_REQUEST * interval_seconds))
                batch = client.get_public_candles(
                    product_id,
                    start=forward_cursor,
                    end=batch_end,
                    granularity=granularity,
                    limit=MAX_PUBLIC_CANDLES_PER_REQUEST,
                )
                for candle in batch:
                    candles_by_start[candle.start] = candle
                if not batch:
                    break
                last_start = max(candle.start for candle in batch)
                next_cursor = last_start + interval_seconds
                if next_cursor <= forward_cursor:
                    break
                forward_cursor = next_cursor

    while remaining > 0:
        batch_size = min(remaining, MAX_PUBLIC_CANDLES_PER_REQUEST)
        window_start = window_end - (batch_size * interval_seconds)
        batch = client.get_public_candles(
            product_id,
            start=window_start,
            end=window_end,
            granularity=granularity,
            limit=batch_size,
        )
        for candle in batch:
            candles_by_start[candle.start] = candle
        if not batch:
            break
        remaining -= batch_size
        earliest_start = min(candle.start for candle in batch)
        if earliest_start >= window_end:
            break
        window_end = earliest_start

    if cache_dir is not None and candles_by_start:
        _save_cached_candles(cache_dir, coin=coin, interval=quant.interval, candles=candles_by_start)
    filtered = [
        candle
        for start, candle in sorted(candles_by_start.items(), key=lambda item: item[0])
        if required_start <= start <= end
    ]
    return filtered[-lookback:]


def backfill_candles_window(
    client: CoinbaseAdvancedClient,
    *,
    coin: str,
    quant: QuantSettings,
    start_at: datetime,
    end_at: datetime,
    cache_dir: Path | None = None,
) -> dict[str, float]:
    granularity, interval_seconds = GRANULARITY_BY_INTERVAL.get(quant.interval, ("FIFTEEN_MINUTE", 900))
    start_ts = int(start_at.astimezone(UTC).timestamp())
    end_ts = int(end_at.astimezone(UTC).timestamp())
    product_id = f"{coin.upper()}-PERP-INTX"
    candles_by_start: dict[int, Candle] = (
        _load_cached_candles(cache_dir, coin=coin, interval=quant.interval) if cache_dir is not None else {}
    )
    expected_starts = set(range(start_ts, end_ts, interval_seconds))
    missing_spans: list[tuple[int, int]] = []
    span_start: int | None = None
    for ts in sorted(expected_starts):
        if ts not in candles_by_start:
            if span_start is None:
                span_start = ts
            continue
        if span_start is not None:
            missing_spans.append((span_start, ts))
            span_start = None
    if span_start is not None:
        missing_spans.append((span_start, end_ts))

    for span_start, span_end in missing_spans:
        cursor = span_start
        while cursor < span_end:
            window_end = min(span_end, cursor + (MAX_PUBLIC_CANDLES_PER_REQUEST * interval_seconds))
            batch = client.get_public_candles(
                product_id,
                start=cursor,
                end=window_end,
                granularity=granularity,
                limit=MAX_PUBLIC_CANDLES_PER_REQUEST,
            )
            for candle in batch:
                candles_by_start[candle.start] = candle
            if not batch:
                cursor = window_end
                continue
            last_start = max(candle.start for candle in batch)
            next_cursor = last_start + interval_seconds
            if next_cursor <= cursor:
                cursor = window_end
            else:
                cursor = next_cursor
    if cache_dir is not None and candles_by_start:
        _save_cached_candles(cache_dir, coin=coin, interval=quant.interval, candles=candles_by_start)
    expected_bars = max(int((end_ts - start_ts) / interval_seconds), 1)
    observed = sum(1 for ts in candles_by_start if start_ts <= ts <= end_ts)
    return {
        "candle_start_ts": float(start_ts),
        "candle_end_ts": float(end_ts),
        "candle_expected_bars": float(expected_bars),
        "candle_observed_bars": float(observed),
        "candle_missing_ratio": round(max(expected_bars - observed, 0) / expected_bars, 6),
    }


def normalize_candle_timestamp(raw_start: int) -> datetime | None:
    value = int(raw_start)
    magnitude = abs(value)
    if magnitude >= 1_000_000_000_000:
        return datetime.fromtimestamp(value / 1000.0, tz=UTC)
    if magnitude >= 1_000_000_000:
        return datetime.fromtimestamp(value, tz=UTC)
    return None


def build_time_context_columns(candles: list[Candle]) -> dict[str, np.ndarray]:
    if not candles:
        return {}
    hour_sin = np.zeros(len(candles), dtype=np.float64)
    hour_cos = np.zeros(len(candles), dtype=np.float64)
    weekday_sin = np.zeros(len(candles), dtype=np.float64)
    weekday_cos = np.zeros(len(candles), dtype=np.float64)
    is_weekend = np.zeros(len(candles), dtype=np.float64)
    session_asia = np.zeros(len(candles), dtype=np.float64)
    session_europe = np.zeros(len(candles), dtype=np.float64)
    session_us = np.zeros(len(candles), dtype=np.float64)
    for idx, candle in enumerate(candles):
        timestamp = normalize_candle_timestamp(candle.start)
        if timestamp is None:
            continue
        hour_fraction = (timestamp.hour + (timestamp.minute / 60.0)) / 24.0
        weekday_fraction = timestamp.weekday() / 7.0
        hour_sin[idx] = np.sin(2 * np.pi * hour_fraction)
        hour_cos[idx] = np.cos(2 * np.pi * hour_fraction)
        weekday_sin[idx] = np.sin(2 * np.pi * weekday_fraction)
        weekday_cos[idx] = np.cos(2 * np.pi * weekday_fraction)
        is_weekend[idx] = 1.0 if timestamp.weekday() >= 5 else 0.0
        if 0 <= timestamp.hour < 8:
            session_asia[idx] = 1.0
        elif 8 <= timestamp.hour < 16:
            session_europe[idx] = 1.0
        else:
            session_us[idx] = 1.0
    return {
        "time_hour_sin": hour_sin,
        "time_hour_cos": hour_cos,
        "time_weekday_sin": weekday_sin,
        "time_weekday_cos": weekday_cos,
        "time_is_weekend": is_weekend,
        "time_session_asia": session_asia,
        "time_session_europe": session_europe,
        "time_session_us": session_us,
    }


def shift(values: np.ndarray, periods: int) -> np.ndarray:
    out = np.full(values.shape, np.nan, dtype=np.float64)
    if periods <= 0:
        out[:] = values
        return out
    if periods < len(values):
        out[periods:] = values[:-periods]
    return out


def pct_change(values: np.ndarray, periods: int) -> np.ndarray:
    shifted = shift(values, periods)
    out = np.full(values.shape, np.nan, dtype=np.float64)
    mask = np.isfinite(values) & np.isfinite(shifted) & (shifted != 0)
    out[mask] = (values[mask] / shifted[mask]) - 1.0
    return out
