from __future__ import annotations

import csv
import gzip
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

import httpx
import joblib
import numpy as np

from ....config.models import QuantSettings
from ....shared.protocols import Candle
from .candle_loader import GRANULARITY_BY_INTERVAL, normalize_candle_timestamp, pct_change


BINANCE_FAPI_BASE = "https://fapi.binance.com"
TARDIS_DATASET_BASE = "https://datasets.tardis.dev/v1"
BINANCE_SYMBOL_BY_COIN = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}
ROLLING_DAY_BARS = 96
OUTLIER_ZSCORE = 8.0
TARDIS_DATASET = "derivative_ticker"


@dataclass
class SnapshotFeaturePayload:
    columns: dict[str, np.ndarray]
    sample_weights: np.ndarray | None = None
    quality_summary: dict[str, float] | None = None


class SnapshotFeatureProvider(Protocol):
    def build_feature_payload(
        self,
        *,
        coin: str,
        candles: list[Candle],
        quant: QuantSettings,
    ) -> SnapshotFeaturePayload: ...


class NullSnapshotFeatureProvider:
    def build_feature_payload(
        self,
        *,
        coin: str,
        candles: list[Candle],
        quant: QuantSettings,
    ) -> SnapshotFeaturePayload:
        return SnapshotFeaturePayload(columns={}, sample_weights=None, quality_summary={})


class BinanceSnapshotFeatureProvider:
    def __init__(
        self,
        *,
        timeout: float = 20.0,
        cache_dir: Path | None = None,
        historical_open_interest_source: str = "tardis",
        tardis_api_key: str | None = None,
        tardis_exchange: str = "binance-futures",
    ) -> None:
        self.client = httpx.Client(
            base_url=BINANCE_FAPI_BASE,
            timeout=timeout,
            headers={"User-Agent": "openclaw-trader/quant-intelligence"},
        )
        self.cache_dir = cache_dir
        self.historical_open_interest_source = str(historical_open_interest_source or "tardis").strip().lower()
        self.tardis_api_key = str(tardis_api_key).strip() if tardis_api_key else None
        self.tardis_exchange = str(tardis_exchange or "binance-futures").strip() or "binance-futures"

    def close(self) -> None:
        self.client.close()

    def build_feature_payload(
        self,
        *,
        coin: str,
        candles: list[Candle],
        quant: QuantSettings,
    ) -> SnapshotFeaturePayload:
        if not candles:
            return SnapshotFeaturePayload(columns={}, sample_weights=None, quality_summary={})
        symbol = BINANCE_SYMBOL_BY_COIN.get(coin.upper())
        if symbol is None:
            return SnapshotFeaturePayload(columns={}, sample_weights=None, quality_summary={})
        _, interval_seconds = GRANULARITY_BY_INTERVAL.get(quant.interval, ("FIFTEEN_MINUTE", 900))
        padding_bars = max(ROLLING_DAY_BARS, max(quant.feature_windows or [24]))
        timestamps = [
            int(normalize_candle_timestamp(candle.start).timestamp() * 1000)
            for candle in candles
            if normalize_candle_timestamp(candle.start) is not None
        ]
        if not timestamps:
            return SnapshotFeaturePayload(columns={}, sample_weights=None, quality_summary={})
        start_ms = min(timestamps) - (padding_bars * interval_seconds * 1000)
        end_ms = max(timestamps) + (interval_seconds * 1000)
        cached_series = self._load_or_backfill_series(
            coin=coin,
            symbol=symbol,
            interval=quant.interval,
            start_ms=start_ms,
            end_ms=end_ms,
            quant=quant,
        )
        aligned = self._align_cached_series(cached_series, candles, quant=quant)
        quality_summary = dict(cached_series.get("coverage_summary", {}))
        quality_summary.update(
            {
                "snapshot_rows": float(len(candles)),
                "snapshot_avg_coverage": round(float(np.mean(aligned["coverage"])), 4),
                "snapshot_rejected_rows": float(np.sum(aligned["sample_weights"] <= 0.0)),
                "snapshot_downweighted_rows": float(
                    np.sum((aligned["sample_weights"] > 0.0) & (aligned["sample_weights"] < 1.0))
                ),
                "snapshot_funding_stale_rows": float(np.sum(aligned["funding_stale"] > 0)),
                "snapshot_premium_stale_rows": float(np.sum(aligned["premium_stale"] > 0)),
                "snapshot_window_start_ms": float(start_ms),
                "snapshot_window_end_ms": float(end_ms),
            }
        )
        coverage_manifest = self._coverage_manifest_path(coin=coin, interval=quant.interval)
        if coverage_manifest is not None:
            coverage_manifest.parent.mkdir(parents=True, exist_ok=True)
            coverage_manifest.write_text(json.dumps(quality_summary, ensure_ascii=True, indent=2))
        columns = {
            "market_funding_rate": np.nan_to_num(aligned["funding_rate"], nan=0.0),
            "market_funding_abs": np.nan_to_num(np.abs(aligned["funding_rate"]), nan=0.0),
            "market_premium": np.nan_to_num(aligned["premium"], nan=0.0),
            "market_premium_abs": np.nan_to_num(np.abs(aligned["premium"]), nan=0.0),
            "market_open_interest_change_6": np.nan_to_num(pct_change(aligned["open_interest"], 6), nan=0.0),
            "market_open_interest_change_24": np.nan_to_num(pct_change(aligned["open_interest"], 24), nan=0.0),
            "market_open_interest_change_48": np.nan_to_num(pct_change(aligned["open_interest"], 48), nan=0.0),
            "market_open_interest_change_96": np.nan_to_num(pct_change(aligned["open_interest"], 96), nan=0.0),
            "market_open_interest_change_192": np.nan_to_num(pct_change(aligned["open_interest"], 192), nan=0.0),
            "market_open_interest_change_384": np.nan_to_num(pct_change(aligned["open_interest"], 384), nan=0.0),
            "market_open_interest_change_768": np.nan_to_num(pct_change(aligned["open_interest"], 768), nan=0.0),
            "market_day_volume_change_6": np.nan_to_num(pct_change(aligned["day_volume"], 6), nan=0.0),
            "market_day_volume_change_24": np.nan_to_num(pct_change(aligned["day_volume"], 24), nan=0.0),
            "market_day_volume_change_48": np.nan_to_num(pct_change(aligned["day_volume"], 48), nan=0.0),
            "market_day_volume_change_96": np.nan_to_num(pct_change(aligned["day_volume"], 96), nan=0.0),
            "market_day_volume_change_192": np.nan_to_num(pct_change(aligned["day_volume"], 192), nan=0.0),
            "market_day_volume_change_384": np.nan_to_num(pct_change(aligned["day_volume"], 384), nan=0.0),
            "market_day_volume_change_768": np.nan_to_num(pct_change(aligned["day_volume"], 768), nan=0.0),
            "market_funding_change_48": np.nan_to_num(pct_change(aligned["funding_rate"], 48), nan=0.0),
            "market_funding_change_96": np.nan_to_num(pct_change(aligned["funding_rate"], 96), nan=0.0),
            "market_funding_change_192": np.nan_to_num(pct_change(aligned["funding_rate"], 192), nan=0.0),
            "market_funding_change_384": np.nan_to_num(pct_change(aligned["funding_rate"], 384), nan=0.0),
            "market_premium_change_48": np.nan_to_num(pct_change(aligned["premium"], 48), nan=0.0),
            "market_premium_change_96": np.nan_to_num(pct_change(aligned["premium"], 96), nan=0.0),
            "market_premium_change_192": np.nan_to_num(pct_change(aligned["premium"], 192), nan=0.0),
            "market_premium_change_384": np.nan_to_num(pct_change(aligned["premium"], 384), nan=0.0),
            "market_snapshot_coverage": aligned["coverage"],
            "market_snapshot_missing_any": aligned["missing_any"],
            "market_open_interest_outlier_flag": aligned["oi_outlier"],
            "market_day_volume_outlier_flag": aligned["volume_outlier"],
            "market_funding_outlier_flag": aligned["funding_outlier"],
            "market_funding_stale_flag": aligned["funding_stale"],
            "market_premium_stale_flag": aligned["premium_stale"],
        }
        return SnapshotFeaturePayload(
            columns=columns,
            sample_weights=aligned["sample_weights"],
            quality_summary=quality_summary,
        )

    def backfill_history(
        self,
        *,
        coin: str,
        interval: str,
        start_ms: int,
        end_ms: int,
        quant: QuantSettings,
    ) -> dict[str, Any]:
        symbol = BINANCE_SYMBOL_BY_COIN.get(coin.upper())
        if symbol is None:
            return {}
        payload = self._load_or_backfill_series(
            coin=coin,
            symbol=symbol,
            interval=interval,
            start_ms=start_ms,
            end_ms=end_ms,
            quant=quant,
        )
        summary = dict(payload.get("coverage_summary", {}))
        summary.update(
            {
                "coin": coin.upper(),
                "interval": interval,
                "start_ms": float(start_ms),
                "end_ms": float(end_ms),
            }
        )
        coverage_manifest = self._coverage_manifest_path(coin=coin, interval=interval)
        if coverage_manifest is not None:
            coverage_manifest.parent.mkdir(parents=True, exist_ok=True)
            coverage_manifest.write_text(json.dumps(summary, ensure_ascii=True, indent=2))
        return summary

    def _align_cached_series(
        self,
        cached_series: dict[str, Any],
        candles: list[Candle],
        *,
        quant: QuantSettings,
    ) -> dict[str, np.ndarray]:
        timestamps = [
            int(normalize_candle_timestamp(candle.start).timestamp() * 1000)
            for candle in candles
            if normalize_candle_timestamp(candle.start) is not None
        ]
        funding_rate = _align_series_to_targets(cached_series.get("funding_rates", {}), timestamps)
        premium = _align_series_to_targets(cached_series.get("premiums", {}), timestamps)
        open_interest = _align_series_to_targets(cached_series.get("open_interest", {}), timestamps)
        day_volume = _align_series_to_targets(cached_series.get("day_volumes", {}), timestamps)
        coverage = np.zeros(len(candles), dtype=np.float64)
        for idx in range(len(candles)):
            valid_fields = sum(
                int(np.isfinite(value))
                for value in (funding_rate[idx], premium[idx], open_interest[idx], day_volume[idx])
            )
            coverage[idx] = valid_fields / 4.0
        oi_outlier = _robust_outlier_flag(pct_change(open_interest, 24))
        volume_outlier = _robust_outlier_flag(pct_change(day_volume, 24))
        funding_outlier = _robust_outlier_flag(funding_rate)
        funding_stale = _stale_segment_flag(funding_rate, window=32)
        premium_stale = _stale_segment_flag(premium, window=32)
        missing_any = (
            ~np.isfinite(funding_rate)
            | ~np.isfinite(premium)
            | ~np.isfinite(open_interest)
            | ~np.isfinite(day_volume)
        ).astype(np.float64)
        sample_weights = np.ones(len(candles), dtype=np.float64)
        sample_weights[missing_any > 0] = 0.35
        sample_weights[volume_outlier > 0] = np.minimum(sample_weights[volume_outlier > 0], 0.20)
        sample_weights[funding_outlier > 0] = np.minimum(sample_weights[funding_outlier > 0], 0.50)
        sample_weights[funding_stale > 0] = np.minimum(sample_weights[funding_stale > 0], 0.50)
        sample_weights[premium_stale > 0] = np.minimum(sample_weights[premium_stale > 0], 0.50)
        sample_weights[oi_outlier > 0] = 0.0
        sample_weights[coverage <= 0.0] = 0.0
        return {
            "funding_rate": funding_rate,
            "premium": premium,
            "open_interest": open_interest,
            "day_volume": day_volume,
            "coverage": coverage,
            "oi_outlier": oi_outlier,
            "volume_outlier": volume_outlier,
            "funding_outlier": funding_outlier,
            "funding_stale": funding_stale,
            "premium_stale": premium_stale,
            "missing_any": missing_any,
            "sample_weights": sample_weights,
        }

    def _get_json(self, path: str, params: dict[str, Any]) -> Any:
        response = self.client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    def _fetch_kline_metric(
        self,
        *,
        path: str,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
        value_index: int,
        limit: int = 1500,
    ) -> dict[int, float]:
        cursor = start_ms
        interval_ms = GRANULARITY_BY_INTERVAL.get(interval, ("FIFTEEN_MINUTE", 900))[1] * 1000
        rows: dict[int, float] = {}
        while cursor < end_ms:
            payload = self._get_json(
                path,
                {
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": cursor,
                    "endTime": end_ms,
                    "limit": limit,
                },
            )
            if not payload:
                break
            for entry in payload:
                rows[int(entry[0])] = float(entry[value_index])
            last_open_time = int(payload[-1][0])
            next_cursor = last_open_time + interval_ms
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            if len(payload) < limit:
                break
        return rows

    def _fetch_premium_index_klines(self, *, symbol: str, interval: str, start_ms: int, end_ms: int) -> dict[int, float]:
        return self._fetch_kline_metric(
            path="/fapi/v1/premiumIndexKlines",
            symbol=symbol,
            interval=interval,
            start_ms=start_ms,
            end_ms=end_ms,
            value_index=4,
        )

    def _fetch_quote_volume_klines(self, *, symbol: str, interval: str, start_ms: int, end_ms: int) -> dict[int, float]:
        return self._fetch_kline_metric(
            path="/fapi/v1/klines",
            symbol=symbol,
            interval=interval,
            start_ms=start_ms,
            end_ms=end_ms,
            value_index=7,
        )

    def _fetch_open_interest_hist(
        self,
        *,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
        limit: int = 500,
    ) -> dict[int, float]:
        rows: dict[int, float] = {}
        interval_ms = GRANULARITY_BY_INTERVAL.get(interval, ("FIFTEEN_MINUTE", 900))[1] * 1000
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        retention_window_ms = 25 * 24 * 60 * 60 * 1000
        start_ms = max(start_ms, now_ms - retention_window_ms)
        start_ms = (start_ms // interval_ms) * interval_ms
        end_ms = (end_ms // interval_ms) * interval_ms
        if start_ms >= end_ms:
            return rows
        max_window_ms = 29 * 24 * 60 * 60 * 1000
        segment_start = start_ms
        while segment_start < end_ms:
            segment_end = min(end_ms, segment_start + max_window_ms)
            cursor = segment_start
            while cursor < segment_end:
                request_end = min(segment_end, cursor + (limit * interval_ms))
                payload = self._get_json(
                    "/futures/data/openInterestHist",
                    {
                        "symbol": symbol,
                        "period": interval,
                        "startTime": cursor,
                        "endTime": request_end,
                        "limit": limit,
                    },
                )
                if not payload:
                    break
                last_timestamp = None
                for entry in payload:
                    ts = int(entry["timestamp"])
                    if ts < segment_start or ts > segment_end:
                        continue
                    value = entry.get("sumOpenInterestValue") or entry.get("sumOpenInterest")
                    if value is None:
                        continue
                    rows[ts] = float(value)
                    if last_timestamp is None or ts > last_timestamp:
                        last_timestamp = ts
                if last_timestamp is None:
                    break
                next_cursor = last_timestamp + interval_ms
                if next_cursor <= cursor:
                    break
                cursor = next_cursor
                if len(payload) < limit:
                    break
            if segment_end >= end_ms:
                break
            segment_start = segment_end + interval_ms
        return rows

    def _fetch_funding_rate_hist(
        self,
        *,
        symbol: str,
        start_ms: int,
        end_ms: int,
        limit: int = 1000,
    ) -> dict[int, float]:
        cursor = start_ms
        rows: dict[int, float] = {}
        while cursor < end_ms:
            payload = self._get_json(
                "/fapi/v1/fundingRate",
                {
                    "symbol": symbol,
                    "startTime": cursor,
                    "endTime": end_ms,
                    "limit": limit,
                },
            )
            if not payload:
                break
            for entry in payload:
                ts = int(entry["fundingTime"])
                rows[ts] = float(entry["fundingRate"])
            last_timestamp = int(payload[-1]["fundingTime"])
            next_cursor = last_timestamp + 1
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            if len(payload) < limit:
                break
        return rows

    def _normalized_cache_file(self, *, coin: str, interval: str) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / "normalized" / f"{coin.upper()}_{interval}_hybrid_snapshot.joblib"

    def _coverage_manifest_path(self, *, coin: str, interval: str) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / "coverage" / f"{coin.upper()}_{interval}.json"

    def _raw_binance_metric_path(self, *, metric: str, coin: str, day: datetime) -> Path | None:
        if self.cache_dir is None:
            return None
        return (
            self.cache_dir
            / "raw"
            / "binance"
            / metric
            / coin.upper()
            / f"{day:%Y-%m-%d}.json.gz"
        )

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

    def _missing_marker_path(self, raw_path: Path) -> Path:
        return raw_path.with_suffix(raw_path.suffix + ".missing")

    def _load_or_backfill_series(
        self,
        *,
        coin: str,
        symbol: str,
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

        funding_rates = {int(key): float(value) for key, value in dict(payload.get("funding_rates", {})).items()}
        premiums = {int(key): float(value) for key, value in dict(payload.get("premiums", {})).items()}
        quote_volumes = {int(key): float(value) for key, value in dict(payload.get("quote_volumes", {})).items()}
        open_interest = {int(key): float(value) for key, value in dict(payload.get("open_interest", {})).items()}
        cached_start_ms = int(payload.get("cached_start_ms", end_ms))
        cached_end_ms = int(payload.get("cached_end_ms", start_ms))

        if not funding_rates or start_ms < cached_start_ms or end_ms > cached_end_ms:
            daily_funding = self._load_or_fetch_binance_metric_days(
                metric="funding_rates",
                fetcher=lambda span_start, span_end: self._fetch_funding_rate_hist(
                    symbol=symbol,
                    start_ms=span_start,
                    end_ms=span_end,
                ),
                coin=coin,
                start_ms=start_ms,
                end_ms=end_ms,
            )
            daily_premiums = self._load_or_fetch_binance_metric_days(
                metric="premiums",
                fetcher=lambda span_start, span_end: self._fetch_premium_index_klines(
                    symbol=symbol,
                    interval=interval,
                    start_ms=span_start,
                    end_ms=span_end,
                ),
                coin=coin,
                start_ms=start_ms,
                end_ms=end_ms,
            )
            daily_quote_volumes = self._load_or_fetch_binance_metric_days(
                metric="quote_volumes",
                fetcher=lambda span_start, span_end: self._fetch_quote_volume_klines(
                    symbol=symbol,
                    interval=interval,
                    start_ms=span_start,
                    end_ms=span_end,
                ),
                coin=coin,
                start_ms=start_ms,
                end_ms=end_ms,
            )
            funding_rates.update(daily_funding)
            premiums.update(daily_premiums)
            quote_volumes.update(daily_quote_volumes)

            if self.historical_open_interest_source == "tardis":
                daily_open_interest = self._load_or_fetch_tardis_open_interest_days(
                    coin=coin,
                    symbol=symbol,
                    interval=interval,
                    start_ms=start_ms,
                    end_ms=end_ms,
                )
                open_interest.update(daily_open_interest)
            recent_open_interest = self._load_or_fetch_binance_metric_days(
                metric="open_interest",
                fetcher=lambda span_start, span_end: self._fetch_open_interest_hist(
                    symbol=symbol,
                    interval=interval,
                    start_ms=span_start,
                    end_ms=span_end,
                ),
                coin=coin,
                start_ms=start_ms,
                end_ms=end_ms,
                recent_only_days=29,
            )
            open_interest.update(recent_open_interest)
            cached_start_ms = min(cached_start_ms, start_ms)
            cached_end_ms = max(cached_end_ms, end_ms)

        funding_rates = _trim_series(funding_rates, start_ms=start_ms, end_ms=end_ms)
        premiums = _trim_series(premiums, start_ms=start_ms, end_ms=end_ms)
        quote_volumes = _trim_series(quote_volumes, start_ms=start_ms, end_ms=end_ms)
        open_interest = _trim_series(open_interest, start_ms=start_ms, end_ms=end_ms)
        day_volumes = _rolling_day_notional_volumes(quote_volumes, window_bars=ROLLING_DAY_BARS)
        coverage_summary = self._coverage_summary(
            funding_rates=funding_rates,
            premiums=premiums,
            quote_volumes=quote_volumes,
            open_interest=open_interest,
            start_ms=start_ms,
            end_ms=end_ms,
            interval=interval,
        )
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump(
                {
                    "funding_rates": funding_rates,
                    "premiums": premiums,
                    "quote_volumes": quote_volumes,
                    "open_interest": open_interest,
                    "cached_start_ms": cached_start_ms,
                    "cached_end_ms": cached_end_ms,
                    "coverage_summary": coverage_summary,
                },
                cache_path,
            )
        return {
            "funding_rates": funding_rates,
            "premiums": premiums,
            "quote_volumes": quote_volumes,
            "day_volumes": day_volumes,
            "open_interest": open_interest,
            "coverage_summary": coverage_summary,
        }

    def _load_or_fetch_binance_metric_days(
        self,
        *,
        metric: str,
        fetcher,
        coin: str,
        start_ms: int,
        end_ms: int,
        recent_only_days: int | None = None,
    ) -> dict[int, float]:
        result: dict[int, float] = {}
        missing_days: list[datetime] = []
        for day in _iter_utc_days(start_ms, end_ms):
            if recent_only_days is not None:
                recent_cutoff = datetime.now(UTC) - timedelta(days=recent_only_days)
                if day < recent_cutoff.replace(hour=0, minute=0, second=0, microsecond=0):
                    continue
            raw_path = self._raw_binance_metric_path(metric=metric, coin=coin, day=day)
            if raw_path is not None and raw_path.exists():
                result.update(_load_json_gz_map(raw_path))
            else:
                missing_days.append(day)
        for span_start, span_end in _group_contiguous_day_ranges(missing_days):
            fetched = fetcher(span_start, span_end)
            daily_payloads = _split_series_by_day(fetched)
            for day, payload in daily_payloads.items():
                raw_path = self._raw_binance_metric_path(metric=metric, coin=coin, day=day)
                if raw_path is not None:
                    _save_json_gz_map(raw_path, payload)
                result.update(payload)
        return _trim_series(result, start_ms=start_ms, end_ms=end_ms)

    def _load_or_fetch_tardis_open_interest_days(
        self,
        *,
        coin: str,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
    ) -> dict[int, float]:
        interval_ms = GRANULARITY_BY_INTERVAL.get(interval, ("FIFTEEN_MINUTE", 900))[1] * 1000
        rows: dict[int, float] = {}
        for day in _iter_utc_days(start_ms, end_ms):
            if self.tardis_api_key is None and day.day != 1:
                # Tardis public access only exposes monthly first-day CSVs without an API key.
                continue
            raw_path = self._raw_tardis_path(symbol=symbol, day=day)
            if raw_path is None:
                continue
            missing_path = self._missing_marker_path(raw_path)
            if not raw_path.exists() and not missing_path.exists():
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    self._download_tardis_file(
                        symbol=symbol,
                        day=day,
                        destination=raw_path,
                    )
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code in {401, 403, 404}:
                        missing_path.touch()
                        continue
                    raise
                except httpx.HTTPError:
                    continue
            if not raw_path.exists():
                continue
            rows.update(_load_tardis_open_interest_day(raw_path, interval_ms=interval_ms))
        return _trim_series(rows, start_ms=start_ms, end_ms=end_ms)

    def _download_tardis_file(
        self,
        *,
        symbol: str,
        day: datetime,
        destination: Path,
    ) -> None:
        headers = {"User-Agent": "openclaw-trader/quant-intelligence"}
        if self.tardis_api_key:
            headers["Authorization"] = f"Bearer {self.tardis_api_key}"
        url = (
            f"{TARDIS_DATASET_BASE}/{self.tardis_exchange}/{TARDIS_DATASET}/"
            f"{day:%Y}/{day:%m}/{day:%d}/{symbol.upper()}.csv.gz"
        )
        response = httpx.get(url, headers=headers, timeout=60.0, follow_redirects=True)
        response.raise_for_status()
        destination.write_bytes(response.content)

    def _coverage_summary(
        self,
        *,
        funding_rates: dict[int, float],
        premiums: dict[int, float],
        quote_volumes: dict[int, float],
        open_interest: dict[int, float],
        start_ms: int,
        end_ms: int,
        interval: str,
    ) -> dict[str, float]:
        interval_ms = GRANULARITY_BY_INTERVAL.get(interval, ("FIFTEEN_MINUTE", 900))[1] * 1000
        expected = list(range((start_ms // interval_ms) * interval_ms, (end_ms // interval_ms) * interval_ms, interval_ms))
        if not expected:
            return {}
        metrics = {
            "funding_rates": funding_rates,
            "premiums": premiums,
            "quote_volumes": quote_volumes,
            "open_interest": open_interest,
        }
        summary: dict[str, float] = {}
        for name, series in metrics.items():
            aligned = _align_series_to_targets(series, expected)
            missing_ratio = float(np.mean(~np.isfinite(aligned)))
            stale_ratio = float(np.mean(_stale_segment_flag(aligned, window=32) > 0))
            summary[f"{name}_start_ms"] = float(min(series.keys())) if series else 0.0
            summary[f"{name}_end_ms"] = float(max(series.keys())) if series else 0.0
            summary[f"{name}_missing_ratio"] = round(missing_ratio, 6)
            summary[f"{name}_stale_ratio"] = round(stale_ratio, 6)
        return summary


def build_snapshot_feature_provider(quant: QuantSettings, *, cache_dir: Path | None = None) -> SnapshotFeatureProvider:
    if str(quant.bootstrap_snapshot_exchange or "").lower() == "binance_usdm":
        return BinanceSnapshotFeatureProvider(
            cache_dir=cache_dir,
            historical_open_interest_source=quant.historical_open_interest_source,
            tardis_api_key=quant.tardis_api_key,
            tardis_exchange=quant.tardis_exchange,
        )
    return NullSnapshotFeatureProvider()


def _iter_utc_days(start_ms: int, end_ms: int) -> list[datetime]:
    start_day = datetime.fromtimestamp(start_ms / 1000.0, tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    end_day = datetime.fromtimestamp(max(end_ms - 1, start_ms) / 1000.0, tz=UTC).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    days: list[datetime] = []
    cursor = start_day
    while cursor <= end_day:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _group_contiguous_day_ranges(days: list[datetime]) -> list[tuple[int, int]]:
    if not days:
        return []
    ordered = sorted(days)
    ranges: list[tuple[int, int]] = []
    start = ordered[0]
    end = ordered[0]
    for day in ordered[1:]:
        if day == end + timedelta(days=1):
            end = day
            continue
        ranges.append((int(start.timestamp() * 1000), int((end + timedelta(days=1)).timestamp() * 1000)))
        start = day
        end = day
    ranges.append((int(start.timestamp() * 1000), int((end + timedelta(days=1)).timestamp() * 1000)))
    return ranges


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


def _load_tardis_open_interest_day(path: Path, *, interval_ms: int) -> dict[int, float]:
    rows: dict[int, tuple[int, float]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            raw_open_interest = row.get("open_interest")
            if raw_open_interest in (None, ""):
                continue
            try:
                event_us = int(row.get("timestamp", "0"))
                event_ms = event_us // 1000
                bucket_ms = (event_ms // interval_ms) * interval_ms
                current = rows.get(bucket_ms)
                value = float(raw_open_interest)
            except Exception:
                continue
            if current is None or event_ms >= current[0]:
                rows[bucket_ms] = (event_ms, value)
    return {bucket: value for bucket, (_, value) in rows.items()}


def _align_series_to_targets(series: dict[int, float], target_timestamps: list[int]) -> np.ndarray:
    result = np.full(len(target_timestamps), np.nan, dtype=np.float64)
    if not series or not target_timestamps:
        return result
    ordered = sorted(series.items())
    pointer = 0
    latest = np.nan
    for idx, target in enumerate(target_timestamps):
        while pointer < len(ordered) and ordered[pointer][0] <= target:
            latest = float(ordered[pointer][1])
            pointer += 1
        result[idx] = latest
    return result


def _trim_series(series: dict[int, float], *, start_ms: int, end_ms: int) -> dict[int, float]:
    return {int(ts): float(value) for ts, value in series.items() if start_ms <= int(ts) <= end_ms}


def _rolling_day_notional_volumes(quote_volume_by_ts: dict[int, float], *, window_bars: int) -> dict[int, float]:
    running = Decimal("0")
    queue: list[Decimal] = []
    result: dict[int, float] = {}
    for ts in sorted(quote_volume_by_ts.keys()):
        value = Decimal(str(quote_volume_by_ts[ts]))
        queue.append(value)
        running += value
        if len(queue) > window_bars:
            running -= queue.pop(0)
        result[ts] = float(running)
    return result


def _robust_outlier_flag(values: np.ndarray) -> np.ndarray:
    series = np.asarray(values, dtype=np.float64)
    result = np.zeros(series.shape, dtype=np.float64)
    finite = np.isfinite(series)
    if not np.any(finite):
        return result
    clean = series[finite]
    median = float(np.median(clean))
    mad = float(np.median(np.abs(clean - median)))
    if mad <= 1e-9:
        return result
    zscore = 0.6745 * (series - median) / mad
    result[np.abs(zscore) > OUTLIER_ZSCORE] = 1.0
    return result


def _stale_segment_flag(values: np.ndarray, *, window: int) -> np.ndarray:
    series = np.asarray(values, dtype=np.float64)
    result = np.zeros(series.shape, dtype=np.float64)
    if window <= 1 or len(series) < window:
        return result
    for idx in range(window - 1, len(series)):
        segment = series[idx - window + 1 : idx + 1]
        if not np.all(np.isfinite(segment)):
            continue
        if float(np.max(segment) - np.min(segment)) <= 1e-12:
            result[idx] = 1.0
    return result
