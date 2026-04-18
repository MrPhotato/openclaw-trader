from __future__ import annotations

from typing import Any

import numpy as np
from lightgbm import LGBMClassifier
from sklearn.metrics import f1_score
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from ....config.models import QuantSettings
from .policy import map_regime_labels
from .probabilities import blend_probabilities, predict_base_probabilities, prediction_metrics

INTERVAL_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "6h": 21600,
    "1d": 86400,
}


def fit_base_models(x: np.ndarray, y: np.ndarray, *, quant: QuantSettings) -> dict[str, Any]:
    return fit_base_models_with_weights(x, y, quant=quant, sample_weight=None)


def fit_base_models_with_weights(
    x: np.ndarray,
    y: np.ndarray,
    *,
    quant: QuantSettings,
    sample_weight: np.ndarray | None,
) -> dict[str, Any]:
    unique_classes, counts = np.unique(y, return_counts=True)
    if len(unique_classes) < 2:
        constant_probs = np.zeros(3, dtype=np.float64)
        constant_probs[int(unique_classes[0])] = 1.0 if len(unique_classes) else 1.0
        return {
            "constant_probs": constant_probs,
            "class_distribution": counts.astype(np.float64) / max(np.sum(counts), 1),
        }
    lgbm = LGBMClassifier(
        objective="multiclass",
        num_class=3,
        n_estimators=250,
        learning_rate=0.05,
        num_leaves=31,
        subsample=0.9,
        colsample_bytree=0.9,
        reg_alpha=0.1,
        reg_lambda=0.1,
        random_state=quant.random_seed,
        class_weight="balanced",
        verbosity=-1,
    )
    lgbm_fit_kwargs: dict[str, Any] = {}
    if sample_weight is not None and len(sample_weight) == len(y):
        lgbm_fit_kwargs["sample_weight"] = sample_weight
    lgbm.fit(x, y, **lgbm_fit_kwargs)

    scaler = StandardScaler()
    x_scaled = scaler.fit_transform(x)
    linear = LogisticRegression(
        max_iter=500,
        class_weight="balanced",
        random_state=quant.random_seed,
    )
    linear_fit_kwargs: dict[str, Any] = {}
    if sample_weight is not None and len(sample_weight) == len(y):
        linear_fit_kwargs["sample_weight"] = sample_weight
    linear.fit(x_scaled, y, **linear_fit_kwargs)
    return {
        "lgbm": lgbm,
        "linear": linear,
        "linear_scaler": scaler,
    }


def walk_forward_predictions(
    dataset,
    *,
    quant: QuantSettings,
    regime_state_map: dict[str, str],
    horizon_bars: int,
    time_windows: list[tuple[int, int]] | None = None,
) -> dict[str, Any]:
    total_rows = len(dataset.x)
    min_train = min(quant.min_train_samples, max(80, total_rows - 40))
    if total_rows <= min_train:
        return {
            "count": 0,
            "y": np.empty((0,), dtype=np.int32),
            "net_long_returns": np.empty((0,), dtype=np.float64),
            "net_short_returns": np.empty((0,), dtype=np.float64),
            "regime_state_ids": np.empty((0,), dtype=np.float64),
            "indices": np.empty((0,), dtype=np.int32),
            "timestamps": np.empty((0,), dtype=np.int64),
            "coin_labels": np.asarray([], dtype=object),
            "regime_labels": np.asarray([], dtype=object),
            "lgbm_probs": np.empty((0, 3), dtype=np.float64),
            "linear_probs": np.empty((0, 3), dtype=np.float64),
            "blended_probs": np.empty((0, 3), dtype=np.float64),
            "metrics": {},
            "summary": {},
        }
    rows: list[dict[str, Any]] = []
    embargo = max(int(quant.walk_forward_embargo_bars), int(horizon_bars))
    interval_seconds = int(INTERVAL_SECONDS.get(str(quant.interval), 900))
    timestamps = np.asarray(getattr(dataset, "timestamps", np.arange(total_rows)), dtype=np.int64)
    coin_labels = np.asarray(getattr(dataset, "coin_labels", np.full(total_rows, "", dtype=object)), dtype=object)
    regime_states = np.asarray(
        getattr(dataset, "regime_state_ids", np.full(total_rows, np.nan, dtype=np.float64)),
        dtype=np.float64,
    )
    regime_labels = np.asarray(
        getattr(dataset, "regime_labels", map_regime_labels(regime_states, regime_state_map)),
        dtype=object,
    )
    unique_times, inverse_indices = np.unique(timestamps, return_inverse=True)
    windows: list[tuple[int, int]] = []
    if time_windows:
        windows = [(int(start), int(end)) for start, end in time_windows]
    else:
        cumulative_rows = np.cumsum(np.bincount(inverse_indices, minlength=len(unique_times)))
        min_train_block = int(np.searchsorted(cumulative_rows, min_train, side="left")) + 1
        fold_target = max(2, quant.walk_forward_splits)
        remaining_blocks = max(len(unique_times) - min_train_block, 1)
        fold_size_blocks = max(24, remaining_blocks // fold_target)
        start_block = min_train_block
        while start_block < len(unique_times):
            end_block = min(len(unique_times), start_block + fold_size_blocks)
            windows.append((int(unique_times[start_block]), int(unique_times[end_block - 1])))
            start_block = end_block

    for start_ts, end_ts in windows:
        train_cutoff = start_ts - (embargo * interval_seconds)
        train_mask = timestamps < train_cutoff
        valid_mask = (timestamps >= start_ts) & (timestamps <= end_ts)
        x_train = dataset.x[train_mask]
        y_train = dataset.y[train_mask]
        sample_weight_train = dataset.sample_weights[train_mask]
        x_valid = dataset.x[valid_mask]
        y_valid = dataset.y[valid_mask]
        if len(x_valid) == 0 or len(x_train) < max(8, min_train // 2):
            break
        models = fit_base_models_with_weights(x_train, y_train, quant=quant, sample_weight=sample_weight_train)
        lgbm_probs, linear_probs = predict_base_probabilities(
            models,
            x_valid,
            suppress_feature_name_warnings=True,
        )
        lgbm_pred = np.argmax(lgbm_probs, axis=1)
        linear_pred = np.argmax(linear_probs, axis=1)
        lgbm_f1 = float(f1_score(y_valid, lgbm_pred, average="macro", zero_division=0))
        linear_f1 = float(f1_score(y_valid, linear_pred, average="macro", zero_division=0))
        total_f1 = lgbm_f1 + linear_f1
        lgbm_weight = (lgbm_f1 / total_f1) if total_f1 > 0 else 0.5
        blended_probs = blend_probabilities(lgbm_probs, linear_probs, lgbm_weight=lgbm_weight)
        rows.append(
            {
                "y": y_valid,
                "net_long_returns": dataset.net_long_returns[valid_mask],
                "net_short_returns": dataset.net_short_returns[valid_mask],
                "regime_state_ids": regime_states[valid_mask],
                "indices": dataset.indices[valid_mask],
                "timestamps": timestamps[valid_mask],
                "coin_labels": coin_labels[valid_mask],
                "regime_labels": regime_labels[valid_mask],
                "sample_weights": dataset.sample_weights[valid_mask],
                "lgbm_probs": lgbm_probs,
                "linear_probs": linear_probs,
                "blended_probs": blended_probs,
                "lgbm_weight": lgbm_weight,
            }
        )
    if not rows:
        holdout_start_block = max(1, min(len(unique_times) - 1, int(len(unique_times) * 0.8)))
        holdout_start_ts = int(unique_times[holdout_start_block])
        train_cutoff = holdout_start_ts - (embargo * interval_seconds)
        train_mask = timestamps < train_cutoff
        valid_mask = timestamps >= holdout_start_ts
        models = fit_base_models_with_weights(
            dataset.x[train_mask],
            dataset.y[train_mask],
            quant=quant,
            sample_weight=dataset.sample_weights[train_mask],
        )
        lgbm_probs, linear_probs = predict_base_probabilities(
            models,
            dataset.x[valid_mask],
            suppress_feature_name_warnings=True,
        )
        y_valid = dataset.y[valid_mask]
        lgbm_pred = np.argmax(lgbm_probs, axis=1)
        linear_pred = np.argmax(linear_probs, axis=1)
        lgbm_f1 = float(f1_score(y_valid, lgbm_pred, average="macro", zero_division=0))
        linear_f1 = float(f1_score(y_valid, linear_pred, average="macro", zero_division=0))
        total_f1 = lgbm_f1 + linear_f1
        lgbm_weight = (lgbm_f1 / total_f1) if total_f1 > 0 else 0.5
        rows.append(
            {
                "y": y_valid,
                "net_long_returns": dataset.net_long_returns[valid_mask],
                "net_short_returns": dataset.net_short_returns[valid_mask],
                "regime_state_ids": regime_states[valid_mask],
                "indices": dataset.indices[valid_mask],
                "timestamps": timestamps[valid_mask],
                "coin_labels": coin_labels[valid_mask],
                "regime_labels": regime_labels[valid_mask],
                "sample_weights": dataset.sample_weights[valid_mask],
                "lgbm_probs": lgbm_probs,
                "linear_probs": linear_probs,
                "blended_probs": blend_probabilities(lgbm_probs, linear_probs, lgbm_weight=lgbm_weight),
                "lgbm_weight": lgbm_weight,
            }
        )
    y = np.concatenate([row["y"] for row in rows], axis=0)
    net_long_returns = np.concatenate([row["net_long_returns"] for row in rows], axis=0)
    net_short_returns = np.concatenate([row["net_short_returns"] for row in rows], axis=0)
    regime_state_ids = np.concatenate([row["regime_state_ids"] for row in rows], axis=0)
    indices = np.concatenate([row["indices"] for row in rows], axis=0)
    oof_timestamps = np.concatenate([row["timestamps"] for row in rows], axis=0)
    oof_coin_labels = np.concatenate([row["coin_labels"] for row in rows], axis=0)
    oof_regime_labels = np.concatenate([row["regime_labels"] for row in rows], axis=0)
    sample_weights = np.concatenate([row["sample_weights"] for row in rows], axis=0)
    lgbm_probs = np.concatenate([row["lgbm_probs"] for row in rows], axis=0)
    linear_probs = np.concatenate([row["linear_probs"] for row in rows], axis=0)
    blended_probs = np.concatenate([row["blended_probs"] for row in rows], axis=0)

    metrics = {
        "lgbm": prediction_metrics(y, lgbm_probs, net_long_returns, net_short_returns, sample_weight=sample_weights),
        "linear": prediction_metrics(y, linear_probs, net_long_returns, net_short_returns, sample_weight=sample_weights),
        "blended": prediction_metrics(y, blended_probs, net_long_returns, net_short_returns, sample_weight=sample_weights),
    }
    summary = {
        "rows": int(len(y)),
        "folds": len(rows),
        "embargo_bars": int(embargo),
        "time_blocks": int(len(unique_times)),
        "avg_lgbm_weight": round(float(np.mean([row["lgbm_weight"] for row in rows])), 4),
        "lgbm_accuracy": metrics["lgbm"]["accuracy"],
        "linear_accuracy": metrics["linear"]["accuracy"],
        "blended_accuracy": metrics["blended"]["accuracy"],
        "lgbm_macro_f1": metrics["lgbm"]["macro_f1"],
        "linear_macro_f1": metrics["linear"]["macro_f1"],
        "blended_macro_f1": metrics["blended"]["macro_f1"],
        "blended_trade_precision": metrics["blended"]["trade_precision"],
        "blended_trade_coverage": metrics["blended"]["trade_coverage"],
        "blended_avg_net_return": metrics["blended"]["avg_net_return"],
        "blended_brier": metrics["blended"]["brier"],
        "blended_log_loss": metrics["blended"]["log_loss"],
        "blended_ece": metrics["blended"]["ece"],
    }
    return {
        "count": len(y),
        "y": y,
        "net_long_returns": net_long_returns,
        "net_short_returns": net_short_returns,
        "regime_state_ids": regime_state_ids,
        "indices": indices,
        "timestamps": oof_timestamps,
        "coin_labels": oof_coin_labels,
        "regime_labels": oof_regime_labels,
        "sample_weights": sample_weights,
        "lgbm_probs": lgbm_probs,
        "linear_probs": linear_probs,
        "blended_probs": blended_probs,
        "metrics": metrics,
        "summary": summary,
        "time_windows": windows,
    }
