from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..models import Candle


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
        features[f"ret_{window}"] = _safe_div(close - _shift(close, window), _shift(close, window))
        features[f"vol_{window}"] = _rolling_std(returns_1, window)
        features[f"ma_{window}"] = ma
        volume_ma = _rolling_mean(volume, window)
        volume_std = _rolling_std(volume, window)
        z = np.full(close.shape, np.nan, dtype=np.float64)
        mask = volume_std > 0
        z[mask] = (volume[mask] - volume_ma[mask]) / volume_std[mask]
        features[f"volume_z_{window}"] = z
        rolling_high = _rolling_max(high, window)
        features[f"breakout_{window}"] = _safe_div(close - rolling_high, rolling_high)
        features[f"drawdown_{window}"] = _safe_div(close - _rolling_max(close, window), _rolling_max(close, window))

    for short, long in ((6, 24), (12, 48)):
        if f"ma_{short}" in features and f"ma_{long}" in features:
            features[f"ma_spread_{short}_{long}"] = _safe_div(features[f"ma_{short}"] - features[f"ma_{long}"], features[f"ma_{long}"])

    valid_mask = np.ones(close.shape, dtype=bool)
    for values in features.values():
        valid_mask &= np.isfinite(values)
    return PreparedSeries(close=close, open=open_, high=high, low=low, volume=volume, features=features, valid_mask=valid_mask)


def build_supervised_dataset(
    candles: list[Candle],
    *,
    windows: list[int],
    horizon_bars: int,
    move_threshold_pct: float,
    extra_columns: dict[str, np.ndarray] | None = None,
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
    for idx in range(len(prepared.close) - horizon_bars):
        if not prepared.valid_mask[idx]:
            continue
        row = np.asarray([feature_columns[name][idx] for name in feature_names], dtype=np.float64)
        if not np.all(np.isfinite(row)):
            continue
        future_return = prepared.close[idx + horizon_bars] / prepared.close[idx] - 1.0
        if future_return > move_threshold_pct:
            target = 2  # long
        elif future_return < -move_threshold_pct:
            target = 0  # short
        else:
            target = 1  # flat
        x_rows.append(row)
        y_rows.append(target)
        indices.append(idx)
    if not x_rows:
        return SupervisedDataset(
            x=np.empty((0, len(feature_names)), dtype=np.float64),
            y=np.empty((0,), dtype=np.int32),
            indices=np.empty((0,), dtype=np.int32),
            feature_names=feature_names,
            feature_columns=feature_columns,
        )
    return SupervisedDataset(
        x=np.vstack(x_rows),
        y=np.asarray(y_rows, dtype=np.int32),
        indices=np.asarray(indices, dtype=np.int32),
        feature_names=feature_names,
        feature_columns=feature_columns,
    )
