from __future__ import annotations

import numpy as np

from ...trade_gateway.market_data.models import DataIngestBundle, MarketSnapshotNormalized
from .candle_loader import pct_change


def build_snapshot_feature_columns(
    *,
    market: DataIngestBundle,
    coin: str,
    length: int,
) -> dict[str, np.ndarray]:
    snapshot = market.market.get(coin)
    if snapshot is None or length <= 0:
        return {}
    base = _snapshot_series(snapshot, length)
    features = {
        "market_funding_rate": base["funding_rate"],
        "market_funding_abs": np.abs(base["funding_rate"]),
        "market_premium": base["premium"],
        "market_premium_abs": np.abs(base["premium"]),
        "market_open_interest_change_6": pct_change(base["open_interest"], 6),
        "market_open_interest_change_24": pct_change(base["open_interest"], 24),
        "market_open_interest_change_48": pct_change(base["open_interest"], 48),
        "market_open_interest_change_96": pct_change(base["open_interest"], 96),
        "market_open_interest_change_192": pct_change(base["open_interest"], 192),
        "market_day_volume_change_6": pct_change(base["day_notional_volume"], 6),
        "market_day_volume_change_24": pct_change(base["day_notional_volume"], 24),
        "market_day_volume_change_48": pct_change(base["day_notional_volume"], 48),
        "market_day_volume_change_96": pct_change(base["day_notional_volume"], 96),
        "market_day_volume_change_192": pct_change(base["day_notional_volume"], 192),
        "market_snapshot_coverage": base["snapshot_coverage"],
        "market_snapshot_missing_any": base["missing_any"],
        "market_open_interest_outlier_flag": np.zeros(length, dtype=np.float64),
        "market_day_volume_outlier_flag": np.zeros(length, dtype=np.float64),
        "market_funding_outlier_flag": np.zeros(length, dtype=np.float64),
        "market_funding_stale_flag": np.zeros(length, dtype=np.float64),
        "market_premium_stale_flag": np.zeros(length, dtype=np.float64),
    }
    if coin != "BTC" and "BTC" in market.market:
        reference = _snapshot_series(market.market["BTC"], length)
        ref_oi_24 = pct_change(reference["open_interest"], 24)
        ref_vol_24 = pct_change(reference["day_notional_volume"], 24)
        features.update(
            {
                "btc_market_funding_rate": reference["funding_rate"],
                "btc_market_premium": reference["premium"],
                "btc_market_open_interest_change_24": ref_oi_24,
                "btc_market_day_volume_change_24": ref_vol_24,
                "rel_market_funding_rate_vs_btc": base["funding_rate"] - reference["funding_rate"],
                "rel_market_premium_vs_btc": base["premium"] - reference["premium"],
                "rel_market_open_interest_change_24_vs_btc": features["market_open_interest_change_24"] - ref_oi_24,
                "rel_market_day_volume_change_24_vs_btc": features["market_day_volume_change_24"] - ref_vol_24,
            }
        )
    return features


def _snapshot_series(snapshot: MarketSnapshotNormalized, length: int) -> dict[str, np.ndarray]:
    def repeated(value: str | None) -> np.ndarray:
        return np.full(length, float(value) if value is not None else 0.0, dtype=np.float64)

    fields = (snapshot.funding_rate, snapshot.premium, snapshot.open_interest, snapshot.day_notional_volume)
    valid_field_count = sum(value is not None for value in fields)
    missing_any = 1.0 if valid_field_count < len(fields) else 0.0
    coverage = valid_field_count / len(fields)

    return {
        "funding_rate": repeated(snapshot.funding_rate),
        "premium": repeated(snapshot.premium),
        "open_interest": repeated(snapshot.open_interest),
        "day_notional_volume": repeated(snapshot.day_notional_volume),
        "mark_price": repeated(snapshot.mark_price),
        "snapshot_coverage": np.full(length, coverage, dtype=np.float64),
        "missing_any": np.full(length, missing_any, dtype=np.float64),
    }
