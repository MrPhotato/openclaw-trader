from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Mapping

import numpy as np

from ...shared.protocols import Candle


@dataclass
class PreparedSeries:
    close: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    volume: np.ndarray
    features: dict[str, np.ndarray]
    valid_mask: np.ndarray


@dataclass
class SupervisedDataset:
    x: np.ndarray
    y: np.ndarray
    indices: np.ndarray
    feature_names: list[str]
    feature_columns: dict[str, np.ndarray]
    future_returns: np.ndarray
    net_long_returns: np.ndarray
    net_short_returns: np.ndarray
    sample_weights: np.ndarray
    timestamps: np.ndarray
    coin_labels: np.ndarray
    regime_state_ids: np.ndarray
    regime_labels: np.ndarray


def _normalize_candle_timestamp(raw_start: int) -> datetime | None:
    value = int(raw_start)
    magnitude = abs(value)
    if magnitude >= 1_000_000_000_000:
        return datetime.fromtimestamp(value / 1000.0, tz=UTC)
    if magnitude >= 1_000_000_000:
        return datetime.fromtimestamp(value, tz=UTC)
    return None


def _arr(values: list[float]) -> np.ndarray:
    return np.asarray(values, dtype=np.float64)


def _rolling_mean(values: np.ndarray, window: int) -> np.ndarray:
    out = np.full(values.shape, np.nan, dtype=np.float64)
    if window <= 0 or len(values) < window:
        return out
    cumsum = np.cumsum(values, dtype=np.float64)
    for idx in range(window - 1, len(values)):
        total = cumsum[idx] - (cumsum[idx - window] if idx >= window else 0.0)
        out[idx] = total / window
    return out


def _rolling_std(values: np.ndarray, window: int) -> np.ndarray:
    out = np.full(values.shape, np.nan, dtype=np.float64)
    if window <= 1 or len(values) < window:
        return out
    for idx in range(window - 1, len(values)):
        segment = values[idx - window + 1 : idx + 1]
        out[idx] = float(np.std(segment, ddof=0))
    return out


def _rolling_max(values: np.ndarray, window: int) -> np.ndarray:
    out = np.full(values.shape, np.nan, dtype=np.float64)
    if window <= 0 or len(values) < window:
        return out
    for idx in range(window - 1, len(values)):
        out[idx] = float(np.max(values[idx - window + 1 : idx + 1]))
    return out


def _rolling_min(values: np.ndarray, window: int) -> np.ndarray:
    out = np.full(values.shape, np.nan, dtype=np.float64)
    if window <= 0 or len(values) < window:
        return out
    for idx in range(window - 1, len(values)):
        out[idx] = float(np.min(values[idx - window + 1 : idx + 1]))
    return out


def _rolling_zscore(values: np.ndarray, window: int) -> np.ndarray:
    mean = _rolling_mean(values, window)
    std = _rolling_std(values, window)
    out = np.zeros(values.shape, dtype=np.float64)
    mask = np.isfinite(values) & np.isfinite(mean) & np.isfinite(std) & (std > 0)
    out[mask] = (values[mask] - mean[mask]) / std[mask]
    return out


def _shift(values: np.ndarray, periods: int) -> np.ndarray:
    out = np.full(values.shape, np.nan, dtype=np.float64)
    if periods <= 0:
        out[:] = values
        return out
    if periods < len(values):
        out[periods:] = values[:-periods]
    return out


def _safe_div(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    out = np.full(num.shape, np.nan, dtype=np.float64)
    mask = den != 0
    out[mask] = num[mask] / den[mask]
    return out


def prepare_series(candles: list[Candle], windows: list[int]) -> PreparedSeries:
    close = _arr([float(item.close) for item in candles])
    open_ = _arr([float(item.open) for item in candles])
    high = _arr([float(item.high) for item in candles])
    low = _arr([float(item.low) for item in candles])
    volume = _arr([float(item.volume) for item in candles])

    returns_1 = np.full(close.shape, np.nan, dtype=np.float64)
    if len(close) > 1:
        returns_1[1:] = close[1:] / close[:-1] - 1.0

    features: dict[str, np.ndarray] = {
        "ret_1": returns_1,
        "range_1": _safe_div(high - low, close),
        "body_1": _safe_div(close - open_, open_),
    }

    prev_volume = _shift(volume, 1)
    features["vol_change_1"] = _safe_div(volume - prev_volume, prev_volume)

    for window in windows:
        if window <= 1:
            continue
        ma = _rolling_mean(close, window)
        rolling_range = _rolling_mean(features["range_1"], window)
        features[f"ret_{window}"] = _safe_div(close - _shift(close, window), _shift(close, window))
        features[f"vol_{window}"] = _rolling_std(returns_1, window)
        features[f"ma_{window}"] = ma
        features[f"range_mean_{window}"] = rolling_range
        features[f"trend_persistence_{window}"] = _rolling_mean(np.sign(np.nan_to_num(returns_1, nan=0.0)), window)
        volume_ma = _rolling_mean(volume, window)
        volume_std = _rolling_std(volume, window)
        z = np.full(close.shape, np.nan, dtype=np.float64)
        mask = volume_std > 0
        z[mask] = (volume[mask] - volume_ma[mask]) / volume_std[mask]
        features[f"volume_z_{window}"] = z
        rolling_high = _rolling_max(high, window)
        rolling_low = _rolling_min(low, window)
        features[f"breakout_{window}"] = _safe_div(close - rolling_high, rolling_high)
        features[f"breakdown_{window}"] = _safe_div(close - rolling_low, rolling_low)
        features[f"drawdown_{window}"] = _safe_div(close - _rolling_max(close, window), _rolling_max(close, window))

    for short, long in ((6, 24), (12, 48)):
        if f"ma_{short}" in features and f"ma_{long}" in features:
            features[f"ma_spread_{short}_{long}"] = _safe_div(features[f"ma_{short}"] - features[f"ma_{long}"], features[f"ma_{long}"])
        if f"vol_{short}" in features and f"vol_{long}" in features:
            features[f"vol_ratio_{short}_{long}"] = _safe_div(features[f"vol_{short}"], features[f"vol_{long}"]) - 1.0
        if f"range_mean_{short}" in features and f"range_mean_{long}" in features:
            features[f"range_ratio_{short}_{long}"] = _safe_div(features[f"range_mean_{short}"], features[f"range_mean_{long}"]) - 1.0
        if f"volume_z_{short}" in features and f"volume_z_{long}" in features:
            features[f"volume_impulse_{short}_{long}"] = features[f"volume_z_{short}"] - features[f"volume_z_{long}"]
        if f"ret_{short}" in features and f"ret_{long}" in features:
            features[f"momentum_spread_{short}_{long}"] = features[f"ret_{short}"] - features[f"ret_{long}"]

    valid_mask = np.ones(close.shape, dtype=bool)
    for values in features.values():
        valid_mask &= np.isfinite(values)
    return PreparedSeries(close=close, open=open_, high=high, low=low, volume=volume, features=features, valid_mask=valid_mask)


def build_reference_feature_columns(
    primary: PreparedSeries,
    reference: PreparedSeries,
    *,
    prefix: str = "btc",
) -> dict[str, np.ndarray]:
    if len(primary.close) != len(reference.close):
        raise ValueError("reference series must align with primary series length")
    primary_feature_map = dict(primary.features)
    reference_feature_map = dict(reference.features)
    primary_feature_map.update(build_long_horizon_feature_columns(primary))
    reference_feature_map.update(build_long_horizon_feature_columns(reference))
    features: dict[str, np.ndarray] = {}
    for name in (
        "ret_6",
        "ret_24",
        "ret_96",
        "ret_192",
        "ret_384",
        "ret_768",
        "ma_spread_6_24",
        "vol_ratio_6_24",
        "range_ratio_6_24",
        "trend_persistence_24",
        "trend_persistence_96",
        "trend_persistence_192",
        "trend_persistence_384",
        "drawdown_96",
        "drawdown_192",
        "drawdown_384",
        "drawdown_768",
    ):
        ref_values = reference_feature_map.get(name)
        own_values = primary_feature_map.get(name)
        if ref_values is None:
            continue
        features[f"{prefix}_{name}"] = ref_values
        if own_values is not None:
            features[f"rel_{name}_vs_{prefix}"] = own_values - ref_values
    return features


def build_asset_indicator_columns(*, coin: str, length: int) -> dict[str, np.ndarray]:
    target = coin.upper()
    return {
        "asset_is_btc": np.full(length, 1.0 if target == "BTC" else 0.0, dtype=np.float64),
        "asset_is_eth": np.full(length, 1.0 if target == "ETH" else 0.0, dtype=np.float64),
        "asset_is_sol": np.full(length, 1.0 if target == "SOL" else 0.0, dtype=np.float64),
    }


def _column_or_zeros(columns: Mapping[str, np.ndarray], name: str, length: int) -> np.ndarray:
    values = columns.get(name)
    if values is None or len(values) != length:
        return np.zeros(length, dtype=np.float64)
    return np.nan_to_num(np.asarray(values, dtype=np.float64), nan=0.0)


def build_interaction_feature_columns(
    prepared: PreparedSeries,
    columns: Mapping[str, np.ndarray],
) -> dict[str, np.ndarray]:
    length = len(prepared.close)
    if length == 0:
        return {}

    jump_abs = np.abs(np.nan_to_num(prepared.features.get("ret_1", np.zeros(length, dtype=np.float64)), nan=0.0))
    jump_z_12 = _rolling_zscore(jump_abs, 12)
    jump_tail_6 = np.nan_to_num(_rolling_max(jump_abs, 6), nan=0.0)
    jump_tail_24 = np.nan_to_num(_rolling_max(jump_abs, 24), nan=0.0)

    time_session_asia = _column_or_zeros(columns, "time_session_asia", length)
    time_session_europe = _column_or_zeros(columns, "time_session_europe", length)
    time_session_us = _column_or_zeros(columns, "time_session_us", length)
    time_is_weekend = _column_or_zeros(columns, "time_is_weekend", length)
    volume_impulse = _column_or_zeros(columns, "volume_impulse_6_24", length)
    range_ratio = _column_or_zeros(columns, "range_ratio_6_24", length)
    vol_ratio = _column_or_zeros(columns, "vol_ratio_6_24", length)
    funding_abs = _column_or_zeros(columns, "market_funding_abs", length)
    premium_abs = _column_or_zeros(columns, "market_premium_abs", length)

    return {
        "jump_abs_1": jump_abs,
        "jump_z_12": jump_z_12,
        "jump_tail_6": jump_tail_6,
        "jump_tail_24": jump_tail_24,
        "time_session_asia_x_volume_impulse_6_24": time_session_asia * volume_impulse,
        "time_session_europe_x_volume_impulse_6_24": time_session_europe * volume_impulse,
        "time_session_us_x_volume_impulse_6_24": time_session_us * volume_impulse,
        "time_session_us_x_range_ratio_6_24": time_session_us * range_ratio,
        "time_is_weekend_x_vol_ratio_6_24": time_is_weekend * vol_ratio,
        "time_is_weekend_x_range_ratio_6_24": time_is_weekend * range_ratio,
        "jump_z_12_x_market_funding_abs": jump_z_12 * funding_abs,
        "jump_z_12_x_market_premium_abs": jump_z_12 * premium_abs,
        "time_session_us_x_market_funding_abs": time_session_us * funding_abs,
        "time_session_asia_x_market_premium_abs": time_session_asia * premium_abs,
    }


def build_long_horizon_feature_columns(prepared: PreparedSeries) -> dict[str, np.ndarray]:
    length = len(prepared.close)
    if length == 0:
        return {}

    def pct(values: np.ndarray, periods: int) -> np.ndarray:
        shifted = _shift(values, periods)
        output = np.full(values.shape, np.nan, dtype=np.float64)
        mask = np.isfinite(values) & np.isfinite(shifted) & (shifted != 0)
        output[mask] = (values[mask] / shifted[mask]) - 1.0
        return np.nan_to_num(output, nan=0.0)

    close = prepared.close
    range_1 = np.nan_to_num(prepared.features.get("range_1", np.zeros(length, dtype=np.float64)), nan=0.0)
    returns_1 = np.nan_to_num(prepared.features.get("ret_1", np.zeros(length, dtype=np.float64)), nan=0.0)
    return {
        "ret_96": pct(close, 96),
        "ret_192": pct(close, 192),
        "ret_384": pct(close, 384),
        "ret_768": pct(close, 768),
        "vol_96": np.nan_to_num(_rolling_std(returns_1, 96), nan=0.0),
        "vol_192": np.nan_to_num(_rolling_std(returns_1, 192), nan=0.0),
        "vol_384": np.nan_to_num(_rolling_std(returns_1, 384), nan=0.0),
        "vol_768": np.nan_to_num(_rolling_std(returns_1, 768), nan=0.0),
        "drawdown_96": np.nan_to_num(_safe_div(close - _rolling_max(close, 96), _rolling_max(close, 96)), nan=0.0),
        "drawdown_192": np.nan_to_num(_safe_div(close - _rolling_max(close, 192), _rolling_max(close, 192)), nan=0.0),
        "drawdown_384": np.nan_to_num(
            _safe_div(close - _rolling_max(close, 384), _rolling_max(close, 384)),
            nan=0.0,
        ),
        "drawdown_768": np.nan_to_num(
            _safe_div(close - _rolling_max(close, 768), _rolling_max(close, 768)),
            nan=0.0,
        ),
        "range_mean_96": np.nan_to_num(_rolling_mean(range_1, 96), nan=0.0),
        "range_mean_192": np.nan_to_num(_rolling_mean(range_1, 192), nan=0.0),
        "range_mean_384": np.nan_to_num(_rolling_mean(range_1, 384), nan=0.0),
        "range_mean_768": np.nan_to_num(_rolling_mean(range_1, 768), nan=0.0),
        "trend_persistence_96": np.nan_to_num(
            _rolling_mean(np.sign(np.nan_to_num(returns_1, nan=0.0)), 96),
            nan=0.0,
        ),
        "trend_persistence_192": np.nan_to_num(
            _rolling_mean(np.sign(np.nan_to_num(returns_1, nan=0.0)), 192),
            nan=0.0,
        ),
        "trend_persistence_384": np.nan_to_num(
            _rolling_mean(np.sign(np.nan_to_num(returns_1, nan=0.0)), 384),
            nan=0.0,
        ),
        "trend_persistence_768": np.nan_to_num(
            _rolling_mean(np.sign(np.nan_to_num(returns_1, nan=0.0)), 768),
            nan=0.0,
        ),
    }


def build_adaptive_move_thresholds(
    prepared: PreparedSeries,
    *,
    base_threshold_pct: float,
    horizon_bars: int,
    volatility_window: int,
    floor_multiplier: float,
    cap_multiplier: float,
) -> tuple[np.ndarray, dict[str, float]]:
    ret_1 = np.nan_to_num(prepared.features.get("ret_1", np.zeros(len(prepared.close), dtype=np.float64)), nan=0.0)
    range_1 = np.nan_to_num(prepared.features.get("range_1", np.zeros(len(prepared.close), dtype=np.float64)), nan=0.0)
    rolling_vol = np.nan_to_num(_rolling_std(ret_1, volatility_window), nan=0.0)
    rolling_range = np.nan_to_num(_rolling_mean(range_1, volatility_window), nan=0.0)
    horizon_scale = float(np.sqrt(max(horizon_bars, 1)))
    volatility_proxy = np.maximum(rolling_vol * horizon_scale, rolling_range * horizon_scale)
    finite_proxy = volatility_proxy[np.isfinite(volatility_proxy) & (volatility_proxy > 0)]
    median_proxy = float(np.median(finite_proxy)) if len(finite_proxy) else float(base_threshold_pct)
    if median_proxy <= 1e-9:
        median_proxy = float(base_threshold_pct)
    anchor_scale = float(base_threshold_pct) / median_proxy
    raw_thresholds = volatility_proxy * anchor_scale
    floor_value = float(base_threshold_pct) * float(floor_multiplier)
    cap_value = float(base_threshold_pct) * float(cap_multiplier)
    clipped = np.clip(raw_thresholds, floor_value, cap_value)
    thresholds = np.where(np.isfinite(clipped) & (clipped > 0), clipped, float(base_threshold_pct))
    diagnostics = {
        "median_proxy": round(median_proxy, 6),
        "anchor_scale": round(anchor_scale, 6),
        "floor_threshold": round(floor_value, 6),
        "cap_threshold": round(cap_value, 6),
        "mean_threshold": round(float(np.mean(thresholds)) if len(thresholds) else float(base_threshold_pct), 6),
    }
    return thresholds.astype(np.float64), diagnostics


def build_supervised_dataset(
    candles: list[Candle],
    *,
    windows: list[int],
    horizon_bars: int,
    move_threshold_pct: float,
    move_thresholds: np.ndarray | None = None,
    round_trip_cost_pct: float = 0.0,
    extra_columns: dict[str, np.ndarray] | None = None,
    row_weights: np.ndarray | None = None,
    coin_label: str | None = None,
    regime_state_map: dict[str, str] | None = None,
) -> SupervisedDataset:
    prepared = prepare_series(candles, windows)
    feature_names = sorted(prepared.features.keys())
    feature_columns = {name: prepared.features[name] for name in feature_names}
    if extra_columns:
        for name, values in extra_columns.items():
            if len(values) != len(prepared.close):
                raise ValueError(f"extra feature {name} has incompatible length")
            feature_names.append(name)
            feature_columns[name] = values.astype(np.float64)
    x_rows: list[np.ndarray] = []
    y_rows: list[int] = []
    indices: list[int] = []
    future_returns: list[float] = []
    net_long_returns: list[float] = []
    net_short_returns: list[float] = []
    sample_weights: list[float] = []
    timestamps: list[int] = []
    coin_labels: list[str] = []
    regime_state_ids: list[float] = []
    regime_labels: list[str] = []
    for idx in range(len(prepared.close) - horizon_bars):
        if not prepared.valid_mask[idx]:
            continue
        quality_weight = 1.0
        if row_weights is not None:
            quality_weight = float(row_weights[idx])
            if not np.isfinite(quality_weight) or quality_weight <= 0:
                continue
        row = np.asarray([feature_columns[name][idx] for name in feature_names], dtype=np.float64)
        if not np.all(np.isfinite(row)):
            continue
        future_return = prepared.close[idx + horizon_bars] / prepared.close[idx] - 1.0
        net_long = future_return - round_trip_cost_pct
        net_short = -future_return - round_trip_cost_pct
        current_move_threshold = float(move_thresholds[idx]) if move_thresholds is not None else float(move_threshold_pct)
        effective_move_threshold = current_move_threshold + round_trip_cost_pct
        if future_return > effective_move_threshold:
            target = 2
        elif future_return < -effective_move_threshold:
            target = 0
        else:
            target = 1
        x_rows.append(row)
        y_rows.append(target)
        indices.append(idx)
        future_returns.append(float(future_return))
        net_long_returns.append(float(net_long))
        net_short_returns.append(float(net_short))
        sample_weights.append(float(quality_weight))
        normalized_timestamp = _normalize_candle_timestamp(candles[idx].start)
        timestamps.append(
            int(normalized_timestamp.timestamp()) if normalized_timestamp is not None else int(candles[idx].start)
        )
        coin_labels.append((coin_label or "").upper())
        regime_state = feature_columns.get("regime_state")
        state_id = float(regime_state[idx]) if regime_state is not None else np.nan
        regime_state_ids.append(state_id)
        if np.isfinite(state_id) and regime_state_map:
            regime_labels.append(regime_state_map.get(str(int(state_id)), "neutral_consolidation"))
        else:
            regime_labels.append("neutral_consolidation")
    if not x_rows:
        return SupervisedDataset(
            x=np.empty((0, len(feature_names)), dtype=np.float64),
            y=np.empty((0,), dtype=np.int32),
            indices=np.empty((0,), dtype=np.int32),
            feature_names=feature_names,
            feature_columns=feature_columns,
            future_returns=np.empty((0,), dtype=np.float64),
            net_long_returns=np.empty((0,), dtype=np.float64),
            net_short_returns=np.empty((0,), dtype=np.float64),
            sample_weights=np.empty((0,), dtype=np.float64),
            timestamps=np.empty((0,), dtype=np.int64),
            coin_labels=np.empty((0,), dtype=object),
            regime_state_ids=np.empty((0,), dtype=np.float64),
            regime_labels=np.empty((0,), dtype=object),
        )
    return SupervisedDataset(
        x=np.vstack(x_rows),
        y=np.asarray(y_rows, dtype=np.int32),
        indices=np.asarray(indices, dtype=np.int32),
        feature_names=feature_names,
        feature_columns=feature_columns,
        future_returns=np.asarray(future_returns, dtype=np.float64),
        net_long_returns=np.asarray(net_long_returns, dtype=np.float64),
        net_short_returns=np.asarray(net_short_returns, dtype=np.float64),
        sample_weights=np.asarray(sample_weights, dtype=np.float64),
        timestamps=np.asarray(timestamps, dtype=np.int64),
        coin_labels=np.asarray(coin_labels, dtype=object),
        regime_state_ids=np.asarray(regime_state_ids, dtype=np.float64),
        regime_labels=np.asarray(regime_labels, dtype=object),
    )


def combine_supervised_datasets(datasets: dict[str, SupervisedDataset]) -> SupervisedDataset:
    valid_items = [(coin, dataset) for coin, dataset in datasets.items() if len(dataset.x)]
    if not valid_items:
        return SupervisedDataset(
            x=np.empty((0, 0), dtype=np.float64),
            y=np.empty((0,), dtype=np.int32),
            indices=np.empty((0,), dtype=np.int32),
            feature_names=[],
            feature_columns={},
            future_returns=np.empty((0,), dtype=np.float64),
            net_long_returns=np.empty((0,), dtype=np.float64),
            net_short_returns=np.empty((0,), dtype=np.float64),
            sample_weights=np.empty((0,), dtype=np.float64),
            timestamps=np.empty((0,), dtype=np.int64),
            coin_labels=np.empty((0,), dtype=object),
            regime_state_ids=np.empty((0,), dtype=np.float64),
            regime_labels=np.empty((0,), dtype=object),
        )

    feature_names = sorted({name for _coin, dataset in valid_items for name in dataset.feature_names})
    x_blocks: list[np.ndarray] = []
    y_blocks: list[np.ndarray] = []
    index_blocks: list[np.ndarray] = []
    future_return_blocks: list[np.ndarray] = []
    net_long_blocks: list[np.ndarray] = []
    net_short_blocks: list[np.ndarray] = []
    weight_blocks: list[np.ndarray] = []
    timestamp_blocks: list[np.ndarray] = []
    coin_blocks: list[np.ndarray] = []
    regime_blocks: list[np.ndarray] = []
    regime_label_blocks: list[np.ndarray] = []

    for coin, dataset in valid_items:
        aligned = np.zeros((len(dataset.x), len(feature_names)), dtype=np.float64)
        local_index = {name: idx for idx, name in enumerate(dataset.feature_names)}
        for column_idx, name in enumerate(feature_names):
            source_idx = local_index.get(name)
            if source_idx is not None:
                aligned[:, column_idx] = dataset.x[:, source_idx]
        x_blocks.append(aligned)
        y_blocks.append(dataset.y)
        index_blocks.append(dataset.indices)
        future_return_blocks.append(dataset.future_returns)
        net_long_blocks.append(dataset.net_long_returns)
        net_short_blocks.append(dataset.net_short_returns)
        weight_blocks.append(dataset.sample_weights)
        timestamp_blocks.append(dataset.timestamps)
        if len(dataset.coin_labels) == len(dataset.y):
            coin_blocks.append(dataset.coin_labels)
        else:
            coin_blocks.append(np.full(len(dataset.y), coin.upper(), dtype=object))
        regime_blocks.append(dataset.regime_state_ids)
        if len(dataset.regime_labels) == len(dataset.y):
            regime_label_blocks.append(dataset.regime_labels)
        else:
            regime_label_blocks.append(np.full(len(dataset.y), "neutral_consolidation", dtype=object))

    combined = SupervisedDataset(
        x=np.vstack(x_blocks),
        y=np.concatenate(y_blocks, axis=0),
        indices=np.concatenate(index_blocks, axis=0),
        feature_names=feature_names,
        feature_columns={},
        future_returns=np.concatenate(future_return_blocks, axis=0),
        net_long_returns=np.concatenate(net_long_blocks, axis=0),
        net_short_returns=np.concatenate(net_short_blocks, axis=0),
        sample_weights=np.concatenate(weight_blocks, axis=0),
        timestamps=np.concatenate(timestamp_blocks, axis=0),
        coin_labels=np.concatenate(coin_blocks, axis=0),
        regime_state_ids=np.concatenate(regime_blocks, axis=0),
        regime_labels=np.concatenate(regime_label_blocks, axis=0),
    )
    order = np.lexsort((np.asarray(combined.coin_labels, dtype=str), combined.timestamps))
    return SupervisedDataset(
        x=combined.x[order],
        y=combined.y[order],
        indices=combined.indices[order],
        feature_names=combined.feature_names,
        feature_columns=combined.feature_columns,
        future_returns=combined.future_returns[order],
        net_long_returns=combined.net_long_returns[order],
        net_short_returns=combined.net_short_returns[order],
        sample_weights=combined.sample_weights[order],
        timestamps=combined.timestamps[order],
        coin_labels=combined.coin_labels[order],
        regime_state_ids=combined.regime_state_ids[order],
        regime_labels=combined.regime_labels[order],
    )
