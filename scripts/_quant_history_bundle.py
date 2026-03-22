from __future__ import annotations

import json
import ssl
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import certifi
import httpx

from openclaw_trader.config.models import SystemSettings
from openclaw_trader.modules.quant_intelligence.support import (
    backfill_candles_window,
    build_daily_macro_feature_provider,
    build_snapshot_feature_provider,
)
from openclaw_trader.shared.protocols.market_types import Candle


COINS = ("BTC", "ETH", "SOL")
MANIFEST_NAME = "history_bundle_manifest.json"


class PublicCoinbaseCandleClient:
    def __init__(self, *, timeout: float = 20.0) -> None:
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        self._client = httpx.Client(
            base_url="https://api.coinbase.com",
            timeout=timeout,
            verify=ssl_context,
            trust_env=False,
            headers={"User-Agent": "openclaw-trader/qi-history-bundle"},
        )

    def close(self) -> None:
        self._client.close()

    def get_public_candles(
        self,
        product_id: str,
        *,
        start: int,
        end: int,
        granularity: str,
        limit: int | None = None,
    ) -> list[Candle]:
        params: dict[str, Any] = {
            "start": str(start),
            "end": str(end),
            "granularity": granularity,
        }
        if limit is not None:
            params["limit"] = limit
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                response = self._client.get(f"/api/v3/brokerage/market/products/{product_id}/candles", params=params)
                response.raise_for_status()
                candles = [Candle(**payload) for payload in response.json().get("candles", [])]
                return sorted(candles, key=lambda candle: candle.start)
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code not in {429, 500, 502, 503, 504} or attempt >= 4:
                    raise
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt >= 4:
                    raise
            time.sleep(1.5 * (attempt + 1))
        if last_error is not None:
            raise last_error
        return []


def history_window_end(now: datetime | None = None) -> datetime:
    current = (now or datetime.now(UTC)).astimezone(UTC).replace(second=0, microsecond=0)
    minute = (current.minute // 15) * 15
    return current.replace(minute=minute)


def history_window_start(settings: SystemSettings, *, end_at: datetime) -> datetime:
    return end_at - timedelta(days=int(settings.quant.history_backfill_days))


def manifest_path(shared_cache_root: Path) -> Path:
    return shared_cache_root / MANIFEST_NAME


def prepare_history_bundle(
    shared_cache_root: Path,
    *,
    settings: SystemSettings,
    end_at: datetime | None = None,
) -> dict[str, Any]:
    shared_cache_root.mkdir(parents=True, exist_ok=True)
    candles_root = shared_cache_root / "candles"
    snapshots_root = shared_cache_root / "snapshots"
    frozen_end = history_window_end(end_at)
    frozen_start = history_window_start(settings, end_at=frozen_end)

    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "interval": settings.quant.interval,
        "window_start_utc": frozen_start.isoformat(),
        "window_end_utc": frozen_end.isoformat(),
        "history_backfill_days": int(settings.quant.history_backfill_days),
        "candles_cache_dir": str(candles_root),
        "snapshots_cache_dir": str(snapshots_root),
        "free_data_stack_summary": {
            "price": "Coinbase 15m candles",
            "snapshot": "Binance funding/premium/quote_volume/recent_oi",
            "monthly_oi_anchor": "Tardis monthly first-day public CSV",
            "coinalyze_enabled": bool(settings.quant.coinalyze_enabled and settings.quant.coinalyze_api_key),
        },
        "coins": {},
    }

    client = PublicCoinbaseCandleClient()
    snapshot_provider = build_snapshot_feature_provider(settings.quant, cache_dir=snapshots_root)
    daily_macro_provider = build_daily_macro_feature_provider(settings.quant, cache_dir=snapshots_root)
    try:
        for coin in COINS:
            candle_summary = backfill_candles_window(
                client,
                coin=coin,
                quant=settings.quant,
                start_at=frozen_start,
                end_at=frozen_end,
                cache_dir=candles_root,
            )
            snapshot_summary = {}
            if hasattr(snapshot_provider, "backfill_history"):
                snapshot_summary = snapshot_provider.backfill_history(
                    coin=coin,
                    interval=settings.quant.interval,
                    start_ms=int(frozen_start.timestamp() * 1000),
                    end_ms=int(frozen_end.timestamp() * 1000),
                    quant=settings.quant,
                )
            daily_macro_summary = {}
            if hasattr(daily_macro_provider, "backfill_history"):
                daily_macro_summary = daily_macro_provider.backfill_history(
                    coin=coin,
                    interval=settings.quant.interval,
                    start_ms=int(frozen_start.timestamp() * 1000),
                    end_ms=int(frozen_end.timestamp() * 1000),
                    quant=settings.quant,
                )
            manifest["coins"][coin] = {**candle_summary, **snapshot_summary, **daily_macro_summary}
    finally:
        client.close()
        if hasattr(snapshot_provider, "close"):
            snapshot_provider.close()
        if hasattr(daily_macro_provider, "close"):
            daily_macro_provider.close()

    manifest_file = manifest_path(shared_cache_root)
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest
