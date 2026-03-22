from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import httpx
import joblib
import numpy as np

from ....config.models import QuantSettings
from ....shared.protocols import Candle
from .candle_loader import normalize_candle_timestamp, pct_change
from .snapshot_history import (
    BINANCE_SYMBOL_BY_COIN,
    TARDIS_DATASET,
    TARDIS_DATASET_BASE,
    _align_series_to_targets,
    _iter_utc_days,
    _load_tardis_open_interest_day,
    _trim_series,
)


COINALYZE_BASE = "https://api.coinalyze.net/v1"
DAY_MS = 24 * 60 * 60 * 1000
COINALYZE_INTERVAL = "daily"


@dataclass
class DailyMacroFeaturePayload:
    columns: dict[str, np.ndarray]
    quality_summary: dict[str, Any] | None = None


class DailyMacroFeatureProvider(Protocol):
    def build_feature_payload(
        self,
        *,
        coin: str,
        candles: list[Candle],
        quant: QuantSettings,
    ) -> DailyMacroFeaturePayload: ...

    def backfill_history(
        self,
        *,
        coin: str,
        interval: str,
        start_ms: int,
        end_ms: int,
        quant: QuantSettings,
    ) -> dict[str, Any]: ...


class NullDailyMacroFeatureProvider:
    def build_feature_payload(
        self,
        *,
        coin: str,
        candles: list[Candle],
        quant: QuantSettings,
    ) -> DailyMacroFeaturePayload:
        return DailyMacroFeaturePayload(columns={}, quality_summary={})

    def backfill_history(
        self,
        *,
        coin: str,
        interval: str,
        start_ms: int,
        end_ms: int,
        quant: QuantSettings,
    ) -> dict[str, Any]:
        return {}


class FreeDailyMacroDerivativesProvider:
    def __init__(
        self,
        *,
        cache_dir: Path | None = None,
        coinalyze_enabled: bool = True,
        coinalyze_api_key: str | None = None,
        coinalyze_symbols_by_coin: dict[str, str] | None = None,
        tardis_api_key: str | None = None,
        tardis_exchange: str = "binance-futures",
    ) -> None:
        self.cache_dir = cache_dir
        self.coinalyze_enabled = bool(coinalyze_enabled)
        self.coinalyze_api_key = str(coinalyze_api_key).strip() if coinalyze_api_key else None
        self.coinalyze_symbols_by_coin = {
            str(coin).strip().upper(): str(symbol).strip()
            for coin, symbol in dict(coinalyze_symbols_by_coin or {}).items()
            if str(coin).strip() and str(symbol).strip()
        }
        self.tardis_api_key = str(tardis_api_key).strip() if tardis_api_key else None
        self.tardis_exchange = str(tardis_exchange or "binance-futures").strip() or "binance-futures"
        self._coinalyze_client = (
            httpx.Client(
                base_url=COINALYZE_BASE,
                timeout=20.0,
                headers={
                    "User-Agent": "openclaw-trader/quant-intelligence",
                    "api_key": self.coinalyze_api_key or "",
                },
            )
            if self.coinalyze_enabled and self.coinalyze_api_key
            else None
        )
        self._coinalyze_market_symbols: dict[str, str] | None = None

    def close(self) -> None:
        if self._coinalyze_client is not None:
            self._coinalyze_client.close()

    def build_feature_payload(
        self,
        *,
        coin: str,
        candles: list[Candle],
        quant: QuantSettings,
    ) -> DailyMacroFeaturePayload:
        if not candles:
            return DailyMacroFeaturePayload(columns={}, quality_summary={})
        timestamps = [
            int(normalize_candle_timestamp(candle.start).timestamp() * 1000)
            for candle in candles
            if normalize_candle_timestamp(candle.start) is not None
        ]
        if not timestamps:
            return DailyMacroFeaturePayload(columns={}, quality_summary={})
        start_ms = min(timestamps) - (45 * DAY_MS)
        end_ms = max(timestamps) + DAY_MS
        series_payload = self._load_or_backfill_series(
            coin=coin,
            interval=quant.interval,
            start_ms=start_ms,
            end_ms=end_ms,
            quant=quant,
        )
        aligned = self._align_payload(series_payload, timestamps)
        columns = {
            f"daily_oi_change_{days}": np.nan_to_num(
                pct_change(aligned["daily_oi"], 96 * days),
                nan=0.0,
            )
            for days in (1, 7, 14, 30)
        }
        columns.update(
            {
                f"daily_funding_change_{days}": np.nan_to_num(
                    pct_change(aligned["daily_funding"], 96 * days),
                    nan=0.0,
                )
                for days in (1, 7, 14, 30)
            }
        )
        columns.update(
            {
                f"daily_long_short_ratio_change_{days}": np.nan_to_num(
                    pct_change(aligned["daily_long_short_ratio"], 96 * days),
                    nan=0.0,
                )
                for days in (1, 7, 14, 30)
            }
        )
        columns["monthly_oi_anchor_gap"] = np.nan_to_num(
            _safe_pct_gap(aligned["daily_oi"], aligned["monthly_oi_anchor"]),
            nan=0.0,
        )
        columns["days_since_monthly_oi_anchor"] = np.nan_to_num(aligned["days_since_monthly_anchor"], nan=0.0)
        columns["daily_vs_recent_binance_oi_gap"] = np.nan_to_num(
            _safe_pct_gap(aligned["daily_oi"], aligned["recent_binance_daily_oi"]),
            nan=0.0,
        )
        return DailyMacroFeaturePayload(columns=columns, quality_summary=series_payload.get("coverage_summary", {}))

    def backfill_history(
        self,
        *,
        coin: str,
        interval: str,
        start_ms: int,
        end_ms: int,
        quant: QuantSettings,
    ) -> dict[str, Any]:
        payload = self._load_or_backfill_series(
            coin=coin,
            interval=interval,
            start_ms=start_ms,
            end_ms=end_ms,
            quant=quant,
        )
        return dict(payload.get("coverage_summary", {}))

    def _load_or_backfill_series(
        self,
        *,
        coin: str,
        interval: str,
        start_ms: int,
        end_ms: int,
        quant: QuantSettings,
    ) -> dict[str, Any]:
        cache_path = self._normalized_cache_file(coin=coin, interval=interval)
        payload: dict[str, Any] = {}
        if cache_path is not None and cache_path.exists():
            loaded = joblib.load(cache_path)
            if isinstance(loaded, dict):
                payload = loaded

        cached_start_ms = int(payload.get("cached_start_ms", end_ms))
        cached_end_ms = int(payload.get("cached_end_ms", start_ms))
        if not payload or start_ms < cached_start_ms or end_ms > cached_end_ms:
            daily_snapshot = self._build_daily_snapshot_series(coin=coin, interval=interval)
            monthly_anchors = self._load_or_fetch_monthly_oi_anchors(coin=coin, start_ms=start_ms, end_ms=end_ms)
            coinalyze_daily = self._load_or_fetch_coinalyze_daily(coin=coin, start_ms=start_ms, end_ms=end_ms)
            merged = self._merge_daily_series(
                start_ms=start_ms,
                end_ms=end_ms,
                snapshot_series=daily_snapshot,
                monthly_anchors=monthly_anchors,
                coinalyze_daily=coinalyze_daily,
            )
            coverage_summary = self._coverage_summary(
                merged=merged,
                coinalyze_daily=coinalyze_daily,
                monthly_anchors=monthly_anchors,
                start_ms=start_ms,
                end_ms=end_ms,
            )
            payload = {
                **merged,
                "coinalyze_daily": coinalyze_daily,
                "monthly_anchors": monthly_anchors,
                "cached_start_ms": min(cached_start_ms, start_ms),
                "cached_end_ms": max(cached_end_ms, end_ms),
                "coverage_summary": coverage_summary,
            }
            if cache_path is not None:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                joblib.dump(payload, cache_path)
        return {
            **payload,
            "coverage_summary": dict(payload.get("coverage_summary", {})),
        }

    def _build_daily_snapshot_series(self, *, coin: str, interval: str) -> dict[str, dict[int, float]]:
        snapshot_path = self._snapshot_cache_file(coin=coin, interval=interval)
        payload: dict[str, Any] = {}
        if snapshot_path is not None and snapshot_path.exists():
            loaded = joblib.load(snapshot_path)
            if isinstance(loaded, dict):
                payload = loaded
        funding_rates = {int(key): float(value) for key, value in dict(payload.get("funding_rates", {})).items()}
        premiums = {int(key): float(value) for key, value in dict(payload.get("premiums", {})).items()}
        open_interest = {int(key): float(value) for key, value in dict(payload.get("open_interest", {})).items()}
        quote_volumes = {int(key): float(value) for key, value in dict(payload.get("quote_volumes", {})).items()}
        return {
            "daily_funding": _daily_last_value(funding_rates),
            "daily_premium": _daily_last_value(premiums),
            "recent_binance_daily_oi": _daily_last_value(open_interest),
            "daily_quote_volume": _daily_last_value(quote_volumes),
        }

    def _merge_daily_series(
        self,
        *,
        start_ms: int,
        end_ms: int,
        snapshot_series: dict[str, dict[int, float]],
        monthly_anchors: dict[int, float],
        coinalyze_daily: dict[str, dict[int, float]],
    ) -> dict[str, dict[int, float]]:
        day_starts = [
            int(day.timestamp() * 1000)
            for day in _iter_utc_days(start_ms, end_ms)
        ]
        monthly_anchor_daily = _forward_fill_daily(monthly_anchors, day_starts)
        recent_binance_daily_oi = {
            int(ts): float(value)
            for ts, value in dict(snapshot_series.get("recent_binance_daily_oi", {})).items()
        }
        daily_oi = {}
        for ts in day_starts:
            value = None
            if ts in coinalyze_daily.get("daily_oi", {}):
                value = float(coinalyze_daily["daily_oi"][ts])
            elif ts in recent_binance_daily_oi:
                value = float(recent_binance_daily_oi[ts])
            elif ts in monthly_anchor_daily:
                value = float(monthly_anchor_daily[ts])
            if value is not None:
                daily_oi[ts] = float(value)

        daily_funding = {}
        snapshot_daily_funding = dict(snapshot_series.get("daily_funding", {}))
        for ts in day_starts:
            value = None
            if ts in coinalyze_daily.get("daily_funding", {}):
                value = float(coinalyze_daily["daily_funding"][ts])
            elif ts in snapshot_daily_funding:
                value = float(snapshot_daily_funding[ts])
            if value is not None:
                daily_funding[ts] = float(value)

        daily_long_short_ratio = {
            int(ts): float(value)
            for ts, value in dict(coinalyze_daily.get("daily_long_short_ratio", {})).items()
        }
        monthly_gap_source = {
            int(ts): float(value)
            for ts, value in dict(daily_oi).items()
        }
        return {
            "daily_oi": _trim_series(daily_oi, start_ms=start_ms, end_ms=end_ms),
            "daily_funding": _trim_series(daily_funding, start_ms=start_ms, end_ms=end_ms),
            "daily_long_short_ratio": _trim_series(daily_long_short_ratio, start_ms=start_ms, end_ms=end_ms),
            "monthly_oi_anchor": _trim_series(monthly_anchor_daily, start_ms=start_ms, end_ms=end_ms),
            "recent_binance_daily_oi": _trim_series(recent_binance_daily_oi, start_ms=start_ms, end_ms=end_ms),
            "daily_quote_volume": _trim_series(snapshot_series.get("daily_quote_volume", {}), start_ms=start_ms, end_ms=end_ms),
            "monthly_gap_source": _trim_series(monthly_gap_source, start_ms=start_ms, end_ms=end_ms),
        }

    def _align_payload(self, payload: dict[str, Any], target_timestamps: list[int]) -> dict[str, np.ndarray]:
        monthly_anchor = _align_series_to_targets(payload.get("monthly_oi_anchor", {}), target_timestamps)
        recent_binance_daily_oi = _align_series_to_targets(payload.get("recent_binance_daily_oi", {}), target_timestamps)
        latest_anchor_timestamp = _align_anchor_timestamps(payload.get("monthly_oi_anchor", {}), target_timestamps)
        days_since_anchor = np.full(len(target_timestamps), np.nan, dtype=np.float64)
        valid = np.isfinite(latest_anchor_timestamp)
        if np.any(valid):
            days_since_anchor[valid] = (
                (np.asarray(target_timestamps, dtype=np.float64)[valid] - latest_anchor_timestamp[valid]) / DAY_MS
            )
        return {
            "daily_oi": _align_series_to_targets(payload.get("daily_oi", {}), target_timestamps),
            "daily_funding": _align_series_to_targets(payload.get("daily_funding", {}), target_timestamps),
            "daily_long_short_ratio": _align_series_to_targets(payload.get("daily_long_short_ratio", {}), target_timestamps),
            "monthly_oi_anchor": monthly_anchor,
            "recent_binance_daily_oi": recent_binance_daily_oi,
            "days_since_monthly_anchor": days_since_anchor,
        }

    def _load_or_fetch_monthly_oi_anchors(self, *, coin: str, start_ms: int, end_ms: int) -> dict[int, float]:
        symbol = BINANCE_SYMBOL_BY_COIN.get(coin.upper())
        if symbol is None:
            return {}
        rows: dict[int, float] = {}
        anchor_start_ms = start_ms - (32 * DAY_MS)
        for day in _iter_utc_days(anchor_start_ms, end_ms):
            if day.day != 1:
                continue
            raw_path = self._raw_tardis_path(symbol=symbol, day=day)
            if raw_path is None:
                continue
            if not raw_path.exists():
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    self._download_tardis_monthly_file(symbol=symbol, day=day, destination=raw_path)
                except httpx.HTTPStatusError:
                    continue
                except httpx.HTTPError:
                    continue
            if not raw_path.exists():
                continue
            daily_payload = _load_tardis_open_interest_day(raw_path, interval_ms=DAY_MS)
            rows.update(daily_payload)
        return _trim_series(rows, start_ms=anchor_start_ms, end_ms=end_ms)

    def _load_or_fetch_coinalyze_daily(
        self,
        *,
        coin: str,
        start_ms: int,
        end_ms: int,
    ) -> dict[str, dict[int, float]]:
        if not self.coinalyze_enabled or not self.coinalyze_api_key or self._coinalyze_client is None:
            return {"daily_oi": {}, "daily_funding": {}, "daily_long_short_ratio": {}}
        symbol = self._resolve_coinalyze_symbol(coin)
        if symbol is None:
            return {"daily_oi": {}, "daily_funding": {}, "daily_long_short_ratio": {}}
        from_sec = int(start_ms / 1000)
        to_sec = int(end_ms / 1000)
        return {
            "daily_oi": self._load_or_fetch_coinalyze_metric_days(
                metric="open_interest",
                endpoint="/open-interest-history",
                symbol=symbol,
                from_sec=from_sec,
                to_sec=to_sec,
                value_key="c",
                extra_params={"convert_to_usd": "true"},
            ),
            "daily_funding": self._load_or_fetch_coinalyze_metric_days(
                metric="funding_rate",
                endpoint="/funding-rate-history",
                symbol=symbol,
                from_sec=from_sec,
                to_sec=to_sec,
                value_key="c",
            ),
            "daily_long_short_ratio": self._load_or_fetch_coinalyze_metric_days(
                metric="long_short_ratio",
                endpoint="/long-short-ratio-history",
                symbol=symbol,
                from_sec=from_sec,
                to_sec=to_sec,
                value_key="r",
            ),
        }

    def _load_or_fetch_coinalyze_metric_days(
        self,
        *,
        metric: str,
        endpoint: str,
        symbol: str,
        from_sec: int,
        to_sec: int,
        value_key: str,
        extra_params: dict[str, str] | None = None,
    ) -> dict[int, float]:
        result: dict[int, float] = {}
        missing_days: list[datetime] = []
        for day in _iter_utc_days(from_sec * 1000, to_sec * 1000):
            raw_path = self._raw_coinalyze_metric_path(metric=metric, symbol=symbol, day=day)
            if raw_path is not None and raw_path.exists():
                result.update(_load_json_gz_map(raw_path))
            else:
                missing_days.append(day)
        if missing_days:
            params = {
                "symbols": symbol,
                "interval": COINALYZE_INTERVAL,
                "from": str(from_sec),
                "to": str(to_sec),
                **dict(extra_params or {}),
            }
            response = self._coinalyze_client.get(endpoint, params=params)
            response.raise_for_status()
            payload = response.json()
            parsed = _parse_coinalyze_history(payload, value_key=value_key)
            for day, day_payload in _split_series_by_day(parsed).items():
                raw_path = self._raw_coinalyze_metric_path(metric=metric, symbol=symbol, day=day)
                if raw_path is not None:
                    _save_json_gz_map(raw_path, day_payload)
                result.update(day_payload)
        return _trim_series(result, start_ms=from_sec * 1000, end_ms=to_sec * 1000)

    def _resolve_coinalyze_symbol(self, coin: str) -> str | None:
        configured = self.coinalyze_symbols_by_coin.get(coin.upper())
        if configured and any(marker in configured for marker in ("PERP", ".", "_")):
            return configured
        if self._coinalyze_client is None:
            return None
        if self._coinalyze_market_symbols is None:
            response = self._coinalyze_client.get("/future-markets")
            response.raise_for_status()
            markets = response.json()
            resolved: dict[str, str] = {}
            for entry in markets:
                try:
                    base_asset = str(entry.get("base_asset", "")).upper()
                    exchange = str(entry.get("exchange", "")).lower()
                    is_perpetual = bool(entry.get("is_perpetual"))
                    margined = str(entry.get("margined", "")).upper()
                    symbol = str(entry.get("symbol", "")).strip()
                    if exchange != "binance" or not is_perpetual or margined != "STABLE" or not symbol:
                        continue
                except Exception:
                    continue
                resolved.setdefault(base_asset, symbol)
            self._coinalyze_market_symbols = resolved
        return self._coinalyze_market_symbols.get(coin.upper()) or configured

    def _normalized_cache_file(self, *, coin: str, interval: str) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / "normalized" / f"{coin.upper()}_{interval}_daily_macro.joblib"

    def _snapshot_cache_file(self, *, coin: str, interval: str) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / "normalized" / f"{coin.upper()}_{interval}_hybrid_snapshot.joblib"

    def _raw_coinalyze_metric_path(self, *, metric: str, symbol: str, day: datetime) -> Path | None:
        if self.cache_dir is None:
            return None
        safe_symbol = symbol.replace("/", "_")
        return self.cache_dir / "raw" / "coinalyze" / metric / safe_symbol / f"{day:%Y-%m-%d}.json.gz"

    def _raw_tardis_path(self, *, symbol: str, day: datetime) -> Path | None:
        if self.cache_dir is None:
            return None
        return (
            self.cache_dir
            / "raw"
            / "tardis"
            / self.tardis_exchange
            / TARDIS_DATASET
            / f"{day:%Y}"
            / f"{day:%m}"
            / f"{day:%d}"
            / f"{symbol.upper()}.csv.gz"
        )

    def _download_tardis_monthly_file(self, *, symbol: str, day: datetime, destination: Path) -> None:
        headers = {"User-Agent": "openclaw-trader/quant-intelligence"}
        if self.tardis_api_key:
            headers["Authorization"] = f"Bearer {self.tardis_api_key}"
        response = httpx.get(
            f"{TARDIS_DATASET_BASE}/{self.tardis_exchange}/{TARDIS_DATASET}/{day:%Y}/{day:%m}/{day:%d}/{symbol.upper()}.csv.gz",
            headers=headers,
            timeout=60.0,
            follow_redirects=True,
        )
        response.raise_for_status()
        destination.write_bytes(response.content)

    def _coverage_summary(
        self,
        *,
        merged: dict[str, dict[int, float]],
        coinalyze_daily: dict[str, dict[int, float]],
        monthly_anchors: dict[int, float],
        start_ms: int,
        end_ms: int,
    ) -> dict[str, Any]:
        day_targets = [int(day.timestamp() * 1000) for day in _iter_utc_days(start_ms, end_ms)]

        def summarize(name: str, series: dict[int, float]) -> dict[str, float]:
            aligned = _align_series_to_targets(series, day_targets)
            return {
                f"{name}_start_ms": float(min(series.keys())) if series else 0.0,
                f"{name}_end_ms": float(max(series.keys())) if series else 0.0,
                f"{name}_missing_ratio": round(float(np.mean(~np.isfinite(aligned))) if len(aligned) else 1.0, 6),
            }

        summary: dict[str, Any] = {
            "coinalyze_enabled": bool(self.coinalyze_enabled and self.coinalyze_api_key),
            "coinalyze_history_summary": {
                "daily_oi_rows": int(len(coinalyze_daily.get("daily_oi", {}))),
                "daily_funding_rows": int(len(coinalyze_daily.get("daily_funding", {}))),
                "daily_long_short_ratio_rows": int(len(coinalyze_daily.get("daily_long_short_ratio", {}))),
            },
            "tardis_monthly_anchor_summary": {
                "rows": int(len(monthly_anchors)),
                "start_ms": float(min(monthly_anchors.keys())) if monthly_anchors else 0.0,
                "end_ms": float(max(monthly_anchors.keys())) if monthly_anchors else 0.0,
            },
        }
        for metric_name in ("daily_oi", "daily_funding", "daily_long_short_ratio", "monthly_oi_anchor", "recent_binance_daily_oi"):
            summary.update(summarize(metric_name, merged.get(metric_name, {})))
        summary["daily_feature_coverage"] = {
            "oi_missing_ratio": summary.get("daily_oi_missing_ratio", 1.0),
            "funding_missing_ratio": summary.get("daily_funding_missing_ratio", 1.0),
            "long_short_ratio_missing_ratio": summary.get("daily_long_short_ratio_missing_ratio", 1.0),
            "monthly_anchor_missing_ratio": summary.get("monthly_oi_anchor_missing_ratio", 1.0),
        }
        return summary


def build_daily_macro_feature_provider(quant: QuantSettings, *, cache_dir: Path | None = None) -> DailyMacroFeatureProvider:
    if not quant.daily_macro_features_enabled or str(quant.bootstrap_snapshot_exchange or "").lower() != "binance_usdm":
        return NullDailyMacroFeatureProvider()
    return FreeDailyMacroDerivativesProvider(
        cache_dir=cache_dir,
        coinalyze_enabled=quant.coinalyze_enabled,
        coinalyze_api_key=quant.coinalyze_api_key,
        coinalyze_symbols_by_coin=quant.coinalyze_symbols_by_coin,
        tardis_api_key=quant.tardis_api_key,
        tardis_exchange=quant.tardis_exchange,
    )


def _safe_pct_gap(values: np.ndarray, baseline: np.ndarray) -> np.ndarray:
    output = np.full(values.shape, np.nan, dtype=np.float64)
    mask = np.isfinite(values) & np.isfinite(baseline) & (baseline != 0)
    output[mask] = (values[mask] / baseline[mask]) - 1.0
    return output


def _daily_last_value(series: dict[int, float]) -> dict[int, float]:
    daily: dict[int, tuple[int, float]] = {}
    for ts, value in sorted(series.items()):
        day_ts = int(datetime.fromtimestamp(ts / 1000.0, tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        current = daily.get(day_ts)
        if current is None or ts >= current[0]:
            daily[day_ts] = (int(ts), float(value))
    return {day_ts: float(payload[1]) for day_ts, payload in daily.items()}


def _forward_fill_daily(series: dict[int, float], day_starts: list[int]) -> dict[int, float]:
    result: dict[int, float] = {}
    ordered = sorted(series.items())
    pointer = 0
    latest = None
    for day_ts in day_starts:
        while pointer < len(ordered) and ordered[pointer][0] <= day_ts:
            latest = float(ordered[pointer][1])
            pointer += 1
        if latest is not None:
            result[int(day_ts)] = float(latest)
    return result


def _align_anchor_timestamps(series: dict[int, float], target_timestamps: list[int]) -> np.ndarray:
    result = np.full(len(target_timestamps), np.nan, dtype=np.float64)
    if not series or not target_timestamps:
        return result
    ordered = sorted((int(ts), float(value)) for ts, value in series.items())
    pointer = 0
    latest = np.nan
    for idx, target in enumerate(target_timestamps):
        while pointer < len(ordered) and ordered[pointer][0] <= target:
            latest = float(ordered[pointer][0])
            pointer += 1
        result[idx] = latest
    return result


def _parse_coinalyze_history(payload: Any, *, value_key: str) -> dict[int, float]:
    rows: dict[int, float] = {}
    for entry in list(payload or []):
        for point in list(entry.get("history") or []):
            try:
                ts = int(point["t"]) * 1000
                value = float(point[value_key])
            except Exception:
                continue
            rows[int(ts)] = float(value)
    return rows


def _split_series_by_day(series: dict[int, float]) -> dict[datetime, dict[int, float]]:
    payloads: dict[datetime, dict[int, float]] = {}
    for ts, value in sorted(series.items()):
        day = datetime.fromtimestamp(ts / 1000.0, tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        payloads.setdefault(day, {})[int(ts)] = float(value)
    return payloads


def _load_json_gz_map(path: Path) -> dict[int, float]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    return {int(key): float(value) for key, value in dict(payload).items()}


def _save_json_gz_map(path: Path, payload: dict[int, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump({int(key): float(value) for key, value in payload.items()}, handle, ensure_ascii=True)
