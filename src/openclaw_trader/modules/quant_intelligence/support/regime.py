from __future__ import annotations

from typing import Any

import numpy as np
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler

from ....config.models import QuantSettings
from ....shared.protocols import Candle
from ..features import prepare_series


def fit_regime_model(coin: str, candles: list[Candle], *, quant: QuantSettings) -> dict[str, Any]:
    prepared = prepare_series(candles, quant.feature_windows)
    regime_feature_names = [
        name
        for name in ("ret_1", "ret_6", "vol_12", "vol_24", "range_1", "ma_spread_6_24", "range_ratio_6_24", "vol_ratio_6_24")
        if name in prepared.features
    ]
    regime_x_rows: list[np.ndarray] = []
    valid_indices: list[int] = []
    for idx in range(len(prepared.close)):
        if not prepared.valid_mask[idx]:
            continue
        row = np.asarray([prepared.features[name][idx] for name in regime_feature_names], dtype=np.float64)
        if np.all(np.isfinite(row)):
            regime_x_rows.append(row)
            valid_indices.append(idx)
    if len(regime_x_rows) < quant.min_train_samples:
        raise ValueError(f"not enough regime rows for {coin}")
    regime_x = np.vstack(regime_x_rows)
    scaler = StandardScaler()
    regime_scaled = scaler.fit_transform(regime_x)
    hmm = GaussianHMM(
        n_components=quant.regime_states,
        covariance_type="diag",
        n_iter=200,
        random_state=quant.random_seed,
        min_covar=1e-5,
    )
    hmm.fit(regime_scaled)
    state_sequence = hmm.predict(regime_scaled)
    state_probs = hmm.predict_proba(regime_scaled)
    state_map = label_regime_states(state_sequence, regime_scaled, regime_feature_names)
    aligned_state_sequence = np.zeros(len(prepared.close), dtype=np.float64)
    aligned_confidence = np.zeros(len(prepared.close), dtype=np.float64)
    for idx, state_id, probs in zip(valid_indices, state_sequence, state_probs):
        aligned_state_sequence[idx] = float(state_id)
        aligned_confidence[idx] = float(np.max(probs))
    return {
        "scaler": scaler,
        "hmm": hmm,
        "feature_names": regime_feature_names,
        "state_map": state_map,
        "state_sequence": aligned_state_sequence,
        "state_confidence": aligned_confidence,
    }


def label_regime_states(states: np.ndarray, regime_scaled: np.ndarray, feature_names: list[str]) -> dict[str, str]:
    try:
        ret_idx = feature_names.index("ret_6")
    except ValueError:
        ret_idx = feature_names.index("ret_1")
    try:
        vol_idx = feature_names.index("vol_24")
    except ValueError:
        vol_idx = feature_names.index("vol_12")
    state_stats: list[tuple[int, float, float]] = []
    for state_id in sorted(set(int(item) for item in states)):
        mask = states == state_id
        mean_ret = float(np.mean(regime_scaled[mask, ret_idx])) if np.any(mask) else 0.0
        mean_vol = float(np.mean(regime_scaled[mask, vol_idx])) if np.any(mask) else 0.0
        state_stats.append((state_id, mean_ret, mean_vol))
    state_stats.sort(key=lambda item: item[1])
    mapping: dict[str, str] = {}
    if state_stats:
        mapping[str(state_stats[0][0])] = "bearish_breakdown"
        mapping[str(state_stats[-1][0])] = "bullish_trend"
        for state_id, _mean_ret, _mean_vol in state_stats[1:-1]:
            mapping[str(state_id)] = "neutral_consolidation"
        if len(state_stats) == 2:
            missing = {str(item[0]) for item in state_stats} - set(mapping.keys())
            for state_id in missing:
                mapping[state_id] = "neutral_consolidation"
    return mapping
