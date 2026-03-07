from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from hmmlearn.hmm import GaussianHMM
from lightgbm import LGBMClassifier
from sklearn.metrics import accuracy_score, f1_score
from sklearn.preprocessing import StandardScaler

from ..config import MODEL_DIR, RuntimeConfig
from ..models import Candle, RiskProfile, SignalDecision, SignalSide
from ..perps.base import PerpEngine
from .features import build_supervised_dataset, prepare_series


SIDE_BY_CLASS = {0: SignalSide.short, 1: SignalSide.flat, 2: SignalSide.long}
REGIME_LABELS = {
    "bullish_trend": RiskProfile.normal,
    "bearish_breakdown": RiskProfile.normal,
    "neutral_consolidation": RiskProfile.defensive,
}


@dataclass
class PerpModelPrediction:
    signal: SignalDecision
    regime: dict[str, Any]
    diagnostics: dict[str, Any]


class PerpModelService:
    def __init__(self, runtime: RuntimeConfig, engine: PerpEngine) -> None:
        self.runtime = runtime
        self.engine = engine
        self._cache: dict[str, dict[str, Any]] = {}

    def _coin_dir(self, coin: str) -> Path:
        return MODEL_DIR / "perps" / coin.upper()

    def _artifact_paths(self, coin: str) -> dict[str, Path]:
        base = self._coin_dir(coin)
        return {
            "meta": base / "meta.json",
            "regime": base / "regime.joblib",
            "classifier": base / "classifier.joblib",
        }

    def _artifact_is_stale(self, meta: dict[str, Any]) -> bool:
        trained_at_raw = meta.get("trained_at")
        if not trained_at_raw:
            return True
        trained_at = datetime.fromisoformat(str(trained_at_raw))
        if trained_at.tzinfo is None:
            trained_at = trained_at.replace(tzinfo=UTC)
        age = datetime.now(UTC) - trained_at
        return age >= timedelta(minutes=self.runtime.model.retrain_after_minutes)

    def _load_cached(self, coin: str) -> dict[str, Any] | None:
        if coin.upper() in self._cache:
            return self._cache[coin.upper()]
        paths = self._artifact_paths(coin)
        if not all(path.exists() for path in paths.values()):
            return None
        meta = json.loads(paths["meta"].read_text())
        payload = {
            "meta": meta,
            "regime": joblib.load(paths["regime"]),
            "classifier": joblib.load(paths["classifier"]),
        }
        self._cache[coin.upper()] = payload
        return payload

    def _save_payload(self, coin: str, payload: dict[str, Any]) -> dict[str, Any]:
        paths = self._artifact_paths(coin)
        paths["meta"].parent.mkdir(parents=True, exist_ok=True)
        paths["meta"].write_text(json.dumps(payload["meta"], ensure_ascii=False, indent=2))
        joblib.dump(payload["regime"], paths["regime"])
        joblib.dump(payload["classifier"], paths["classifier"])
        self._cache[coin.upper()] = payload
        return payload

    def ensure_models(self, coin: str) -> dict[str, Any]:
        existing = self._load_cached(coin)
        if existing and not self._artifact_is_stale(existing["meta"]):
            return existing
        return self.train_models(coin)

    def train_models(self, coin: str) -> dict[str, Any]:
        candles = self.engine.candles(
            coin,
            interval=self.runtime.model.interval,
            lookback=self.runtime.model.history_bars,
        )
        if len(candles) < self.runtime.model.min_train_samples:
            raise ValueError(f"not enough candles to train model for {coin}: {len(candles)}")

        regime_payload = self._fit_regime_model(coin, candles)
        dataset = build_supervised_dataset(
            candles,
            windows=self.runtime.model.feature_windows,
            horizon_bars=self.runtime.model.forecast_horizon_bars,
            move_threshold_pct=self.runtime.model.target_move_threshold_pct,
            extra_columns={
                "regime_state": regime_payload["state_sequence"],
                "regime_confidence": regime_payload["state_confidence"],
            },
        )
        if len(dataset.x) < self.runtime.model.min_train_samples:
            raise ValueError(f"not enough supervised samples to train model for {coin}: {len(dataset.x)}")

        split_index = max(int(len(dataset.x) * 0.8), self.runtime.model.min_train_samples // 2)
        split_index = min(split_index, len(dataset.x) - 50) if len(dataset.x) > 100 else max(1, len(dataset.x) - 1)
        x_train, x_valid = dataset.x[:split_index], dataset.x[split_index:]
        y_train, y_valid = dataset.y[:split_index], dataset.y[split_index:]

        classifier = LGBMClassifier(
            objective="multiclass",
            num_class=3,
            n_estimators=250,
            learning_rate=0.05,
            num_leaves=31,
            subsample=0.9,
            colsample_bytree=0.9,
            reg_alpha=0.1,
            reg_lambda=0.1,
            random_state=self.runtime.model.random_seed,
            class_weight="balanced",
            verbosity=-1,
        )
        classifier.fit(x_train, y_train)
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="X does not have valid feature names")
            valid_pred = classifier.predict(x_valid)
        valid_acc = float(accuracy_score(y_valid, valid_pred)) if len(y_valid) else 0.0
        valid_f1 = float(f1_score(y_valid, valid_pred, average="macro", zero_division=0)) if len(y_valid) else 0.0

        payload = {
            "meta": {
                "coin": coin.upper(),
                "trained_at": datetime.now(UTC).isoformat(),
                "feature_names": dataset.feature_names,
                "training_rows": int(len(dataset.x)),
                "validation_accuracy": valid_acc,
                "validation_macro_f1": valid_f1,
                "interval": self.runtime.model.interval,
                "history_bars": self.runtime.model.history_bars,
                "forecast_horizon_bars": self.runtime.model.forecast_horizon_bars,
                "move_threshold_pct": self.runtime.model.target_move_threshold_pct,
                "regime_state_map": regime_payload["state_map"],
            },
            "regime": regime_payload,
            "classifier": classifier,
        }
        return self._save_payload(coin, payload)

    def _fit_regime_model(self, coin: str, candles: list[Candle]) -> dict[str, Any]:
        prepared = prepare_series(candles, self.runtime.model.feature_windows)
        regime_feature_names = [name for name in ("ret_1", "ret_6", "vol_12", "vol_24", "range_1", "ma_spread_6_24") if name in prepared.features]
        regime_x_rows: list[np.ndarray] = []
        valid_indices: list[int] = []
        for idx in range(len(prepared.close)):
            if not prepared.valid_mask[idx]:
                continue
            row = np.asarray([prepared.features[name][idx] for name in regime_feature_names], dtype=np.float64)
            if np.all(np.isfinite(row)):
                regime_x_rows.append(row)
                valid_indices.append(idx)
        if len(regime_x_rows) < self.runtime.model.min_train_samples:
            raise ValueError(f"not enough regime rows for {coin}")
        regime_x = np.vstack(regime_x_rows)
        scaler = StandardScaler()
        regime_scaled = scaler.fit_transform(regime_x)
        hmm = GaussianHMM(
            n_components=self.runtime.model.regime_states,
            covariance_type="diag",
            n_iter=200,
            random_state=self.runtime.model.random_seed,
            min_covar=1e-5,
        )
        hmm.fit(regime_scaled)
        state_sequence = hmm.predict(regime_scaled)
        state_probs = hmm.predict_proba(regime_scaled)

        state_map = self._label_regime_states(state_sequence, regime_scaled, regime_feature_names)
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

    def _label_regime_states(self, states: np.ndarray, regime_scaled: np.ndarray, feature_names: list[str]) -> dict[str, str]:
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

    def predict(self, coin: str, *, max_order_quote_usd: Decimal, leverage: Decimal) -> PerpModelPrediction:
        payload = self.ensure_models(coin)
        candles = self.engine.candles(
            coin,
            interval=self.runtime.model.interval,
            lookback=self.runtime.model.history_bars,
        )
        prepared = prepare_series(candles, self.runtime.model.feature_windows)
        regime_bundle = payload["regime"]
        regime_feature_names = regime_bundle["feature_names"]
        feature_names = payload["meta"]["feature_names"]
        latest_idx = self._latest_valid_index(prepared.valid_mask)
        if latest_idx is None:
            raise ValueError(f"no valid feature row for {coin}")

        regime_row = np.asarray([prepared.features[name][latest_idx] for name in regime_feature_names], dtype=np.float64).reshape(1, -1)
        regime_scaled = regime_bundle["scaler"].transform(regime_row)
        regime_state_id = int(regime_bundle["hmm"].predict(regime_scaled)[0])
        regime_prob = regime_bundle["hmm"].predict_proba(regime_scaled)[0]
        regime_label = regime_bundle["state_map"].get(str(regime_state_id), "neutral_consolidation")
        regime_confidence = float(np.max(regime_prob))

        row_features: list[float] = []
        for name in feature_names:
            if name == "regime_state":
                row_features.append(float(regime_state_id))
            elif name == "regime_confidence":
                row_features.append(regime_confidence)
            else:
                row_features.append(float(prepared.features[name][latest_idx]))
        x_now = np.asarray(row_features, dtype=np.float64).reshape(1, -1)
        classifier = payload["classifier"]
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="X does not have valid feature names")
            probabilities = classifier.predict_proba(x_now)[0]
        class_index = int(np.argmax(probabilities))
        top_probability = float(np.max(probabilities))
        side = SIDE_BY_CLASS[class_index]
        long_short_probability = max(float(probabilities[0]), float(probabilities[2]))

        if side == SignalSide.flat or top_probability < self.runtime.model.min_confidence or long_short_probability < self.runtime.model.min_long_short_probability:
            side = SignalSide.flat

        size_ratio = self.runtime.model.order_size_floor_ratio
        if side != SignalSide.flat:
            span = max(1e-6, 1.0 - self.runtime.model.min_confidence)
            normalized = max(0.0, min((top_probability - self.runtime.model.min_confidence) / span, 1.0))
            size_ratio = self.runtime.model.order_size_floor_ratio + (
                (self.runtime.model.order_size_ceiling_ratio - self.runtime.model.order_size_floor_ratio) * normalized
            )
            if regime_label == "neutral_consolidation":
                size_ratio *= self.runtime.model.neutral_regime_size_scale
            if (regime_label == "bullish_trend" and side == SignalSide.short) or (regime_label == "bearish_breakdown" and side == SignalSide.long):
                size_ratio *= self.runtime.model.counter_regime_size_scale
        quote_size = (max_order_quote_usd * Decimal(str(round(size_ratio, 6)))).quantize(Decimal("0.00000001")) if side != SignalSide.flat else Decimal("0")

        risk_profile = REGIME_LABELS.get(regime_label, RiskProfile.normal)
        if side == SignalSide.flat:
            risk_profile = RiskProfile.defensive

        latest_close = prepared.close[latest_idx]
        realized_vol = float(prepared.features.get("vol_24", prepared.features.get("vol_12"))[latest_idx]) if "vol_24" in prepared.features or "vol_12" in prepared.features else 0.01
        stop_loss_pct = max(0.012, min(0.03, realized_vol * 2.2))
        take_profit_pct = max(0.024, min(0.08, stop_loss_pct * 2.2))
        reason = (
            f"LightGBM signal={side.value}, confidence={top_probability:.2f}; "
            f"regime={regime_label}, regime_confidence={regime_confidence:.2f}."
        )
        signal = SignalDecision(
            product_id=f"{coin.upper()}-PERP",
            side=side,
            confidence=round(top_probability, 4),
            reason=reason,
            quote_size_usd=quote_size,
            stop_loss_pct=round(stop_loss_pct, 4),
            take_profit_pct=round(take_profit_pct, 4),
            leverage=leverage,
            risk_profile=risk_profile,
            metadata={
                "model": "lightgbm",
                "regime_model": "gaussian_hmm",
                "regime": regime_label,
                "regime_state_id": regime_state_id,
                "regime_confidence": round(regime_confidence, 4),
                "prob_short": round(float(probabilities[0]), 4),
                "prob_flat": round(float(probabilities[1]), 4),
                "prob_long": round(float(probabilities[2]), 4),
                "latest_price": round(float(latest_close), 6),
                "artifact_trained_at": payload["meta"]["trained_at"],
                "validation_accuracy": payload["meta"]["validation_accuracy"],
                "validation_macro_f1": payload["meta"]["validation_macro_f1"],
            },
        )
        return PerpModelPrediction(
            signal=signal,
            regime={
                "label": regime_label,
                "confidence": round(regime_confidence, 4),
                "state_id": regime_state_id,
            },
            diagnostics={
                "trained_at": payload["meta"]["trained_at"],
                "training_rows": payload["meta"]["training_rows"],
                "validation_accuracy": payload["meta"]["validation_accuracy"],
                "validation_macro_f1": payload["meta"]["validation_macro_f1"],
            },
        )

    def model_status(self, coin: str) -> dict[str, Any]:
        payload = self.ensure_models(coin)
        meta = payload["meta"]
        return {
            "coin": coin.upper(),
            "trained_at": meta["trained_at"],
            "training_rows": meta["training_rows"],
            "validation_accuracy": meta["validation_accuracy"],
            "validation_macro_f1": meta["validation_macro_f1"],
            "feature_names": meta["feature_names"],
            "regime_state_map": meta["regime_state_map"],
        }

    @staticmethod
    def _latest_valid_index(valid_mask: np.ndarray) -> int | None:
        valid_indices = np.where(valid_mask)[0]
        if len(valid_indices) == 0:
            return None
        return int(valid_indices[-1])
