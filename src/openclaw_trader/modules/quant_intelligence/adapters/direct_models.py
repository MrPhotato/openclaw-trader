from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ....config.loader import coerce_system_settings, load_coinbase_credentials, load_system_settings
from ....shared.integrations.coinbase import CoinbaseAdvancedClient
from ..features import (
    build_asset_indicator_columns,
    build_interaction_feature_columns,
    build_long_horizon_feature_columns,
    build_reference_feature_columns,
    prepare_series,
)
from ..models import CoinForecast, HorizonSignal
from ..support import (
    apply_flat_isotonic_rescale,
    apply_dirichlet_calibration,
    blend_probabilities,
    build_meta_features,
    build_snapshot_feature_columns,
    build_time_context_columns,
    evaluate_high_confidence_policy,
    feature_value,
    fetch_candles,
    latest_valid_index,
    load_artifact_payload,
    predict_base_probabilities,
    predict_meta_probability,
)
from ...trade_gateway.market_data.models import DataIngestBundle
from .direct_training import DirectQuantTrainer


SIDE_BY_CLASS = {0: "short", 1: "flat", 2: "long"}
PRIMARY_HORIZON = "1h"


class DirectArtifactQuantProvider:
    def __init__(
        self,
        *,
        client: CoinbaseAdvancedClient | None = None,
        runtime: Any | None = None,
        artifact_root: Path | None = None,
        retrain_provider: Any | None = None,
    ) -> None:
        self.settings = load_system_settings() if runtime is None else coerce_system_settings(runtime)
        self.quant = self.settings.quant
        self.client = client or CoinbaseAdvancedClient(
            self.settings.coinbase or load_coinbase_credentials(self.settings.runtime_root)
        )
        self.artifact_root = artifact_root or (self.settings.paths.model_dir / "perps")
        self.candle_cache_dir = self.settings.paths.data_dir / "quant_candle_cache"
        self.retrain_provider = retrain_provider
        self._artifact_cache: dict[str, dict[str, Any]] = {}

    def predict_market(self, market: DataIngestBundle) -> dict[str, CoinForecast]:
        forecasts: dict[str, CoinForecast] = {}
        target_coins = {coin.upper() for coin in market.market}
        if any(coin != "BTC" for coin in target_coins):
            target_coins.add("BTC")

        candle_cache: dict[str, list] = {}
        prepared_cache: dict[str, Any] = {}
        for coin in sorted(target_coins):
            candles = fetch_candles(
                self.client,
                coin=coin,
                quant=self.quant,
                cache_dir=self.candle_cache_dir,
            )
            candle_cache[coin] = candles
            prepared_cache[coin] = prepare_series(candles, self.quant.feature_windows)

        for coin in sorted(market.market):
            try:
                forecasts[coin] = self._predict_coin(
                    coin=coin,
                    market=market,
                    candle_cache=candle_cache,
                    prepared_cache=prepared_cache,
                )
            except Exception as exc:
                forecasts[coin] = self._flat_forecast(coin, reason=f"quant_prediction_failed:{type(exc).__name__}")
        return forecasts

    def retrain(self, coins: list[str] | None = None) -> dict[str, dict]:
        provider = self.retrain_provider
        if provider is None:
            provider = DirectQuantTrainer(
                client=self.client,
                runtime=self.settings,
                artifact_root=self.artifact_root,
            )
            self.retrain_provider = provider
        result = provider.retrain(coins)
        self._artifact_cache.clear()
        return result

    def _predict_coin(
        self,
        *,
        coin: str,
        market: DataIngestBundle,
        candle_cache: dict[str, list],
        prepared_cache: dict[str, Any],
    ) -> CoinForecast:
        horizons: dict[str, HorizonSignal] = {}
        for horizon in self.quant.forecast_horizons:
            horizons[horizon] = self._predict_horizon(
                coin=coin,
                horizon=horizon,
                market=market,
                candle_cache=candle_cache,
                prepared_cache=prepared_cache,
            )
        return CoinForecast(
            coin=coin,
            horizons=horizons,
            diagnostics={"primary_horizon": PRIMARY_HORIZON, "source": "direct_artifact_provider"},
        )

    def _predict_horizon(
        self,
        *,
        coin: str,
        horizon: str,
        market: DataIngestBundle,
        candle_cache: dict[str, list],
        prepared_cache: dict[str, Any],
    ) -> HorizonSignal:
        payload = self._cached_payload(coin, horizon)
        prepared = prepared_cache[coin]
        latest_idx = latest_valid_index(prepared.valid_mask)
        if latest_idx is None:
            return HorizonSignal(horizon=horizon, side="flat", confidence=0.0, diagnostics={"reason": "no_valid_feature_row"})

        feature_columns = dict(prepared.features)
        feature_columns.update(build_long_horizon_feature_columns(prepared))
        feature_columns.update(build_time_context_columns(candle_cache[coin]))
        feature_columns.update(
            build_snapshot_feature_columns(
                market=market,
                coin=coin,
                length=len(candle_cache[coin]),
            )
        )
        if coin != "BTC" and "BTC" in prepared_cache:
            btc_prepared = prepared_cache["BTC"]
            if len(prepared.close) == len(btc_prepared.close):
                feature_columns.update(build_reference_feature_columns(prepared, btc_prepared, prefix="btc"))
        feature_columns.update(build_asset_indicator_columns(coin=coin, length=len(candle_cache[coin])))
        feature_columns.update(build_interaction_feature_columns(prepared, feature_columns))

        regime_bundle = payload["regime"]
        regime_row = np.asarray(
            [feature_value(feature_columns, name, latest_idx) for name in regime_bundle["feature_names"]],
            dtype=np.float64,
        ).reshape(1, -1)
        regime_scaled = regime_bundle["scaler"].transform(regime_row)
        regime_state_id = int(regime_bundle["hmm"].predict(regime_scaled)[0])
        regime_prob = regime_bundle["hmm"].predict_proba(regime_scaled)[0]
        regime_label = regime_bundle["state_map"].get(str(regime_state_id), "neutral_consolidation")
        regime_confidence = float(regime_prob.max())

        feature_columns["regime_state"] = np.full(prepared.close.shape, float(regime_state_id), dtype=np.float64)
        feature_columns["regime_confidence"] = np.full(prepared.close.shape, regime_confidence, dtype=np.float64)

        feature_names = payload["meta"].get("feature_names", [])
        row = np.asarray(
            [feature_value(feature_columns, name, latest_idx) for name in feature_names],
            dtype=np.float64,
        ).reshape(1, -1)

        classifier_bundle = payload["classifier"]
        base_models = classifier_bundle.get("base_models", classifier_bundle)
        lgbm_probs, linear_probs = predict_base_probabilities(base_models, row)
        blend_weight = float(payload["meta"].get("blend_weight_lgbm", 0.6))
        raw_probabilities = blend_probabilities(lgbm_probs, linear_probs, lgbm_weight=blend_weight)
        specialist_base_models = classifier_bundle.get("specialist_base_models")
        specialist_summary = payload["meta"].get("specialist_summary") or {}
        if specialist_base_models is not None and specialist_summary.get("enabled"):
            specialist_lgbm_probs, specialist_linear_probs = predict_base_probabilities(specialist_base_models, row)
            specialist_base_blend = float(specialist_summary.get("base_blend_weight", 0.6))
            specialist_probabilities = blend_probabilities(
                specialist_lgbm_probs,
                specialist_linear_probs,
                lgbm_weight=specialist_base_blend,
            )
            raw_probabilities = blend_probabilities(
                specialist_probabilities,
                raw_probabilities,
                lgbm_weight=float(specialist_summary.get("blend_weight", 0.5)),
            )
        calibrated_probabilities = apply_dirichlet_calibration(
            classifier_bundle.get("dirichlet_calibrator"),
            raw_probabilities,
        )
        probability_calibration_mode = str(payload["meta"].get("probability_calibration_mode", "dirichlet")).strip().lower()
        if probability_calibration_mode == "flat_isotonic_rescale":
            calibrated_probabilities = apply_flat_isotonic_rescale(
                classifier_bundle.get("flat_class_calibrator"),
                calibrated_probabilities,
            )
        class_index = int(np.argmax(calibrated_probabilities[0]))
        top_probability = float(np.max(calibrated_probabilities[0]))
        side = SIDE_BY_CLASS[class_index]
        proposed_side = side

        meta_features = build_meta_features(calibrated_probabilities)
        meta_probability = float(
            predict_meta_probability(
                classifier_bundle.get("meta_model"),
                classifier_bundle.get("meta_calibrator"),
                meta_features,
            )[0]
        )
        combined_confidence = max(0.0, min((top_probability * 0.65) + (meta_probability * 0.35), 1.0))
        acceptance_policy = payload["meta"].get("acceptance_policy") or {
            "min_top_probability": 0.0,
            "min_margin": 0.0,
            "max_entropy": 1.0,
        }
        acceptance = evaluate_high_confidence_policy(
            calibrated_probabilities,
            acceptance_policy,
            trade_quality=np.asarray([meta_probability], dtype=np.float64),
            regime_labels=np.asarray([regime_label], dtype=object),
        )
        accepted = bool(acceptance["accepted"][0]) if len(acceptance["accepted"]) else True
        abstain_reasons: list[str] = []
        if not accepted:
            if str(acceptance_policy.get("mode", "")).strip() == "score_rank":
                regime_threshold = dict(acceptance_policy.get("regime_min_scores") or {}).get(
                    regime_label,
                    acceptance_policy.get("min_score", 1.0),
                )
                if float(regime_threshold) > float(acceptance["score"][0]):
                    abstain_reasons.append("acceptance_score")
            else:
                if float(acceptance_policy.get("min_top_probability", 0.0)) > float(acceptance["top_probability"][0]):
                    abstain_reasons.append("top_probability")
                if float(acceptance_policy.get("min_margin", 0.0)) > float(acceptance["margin"][0]):
                    abstain_reasons.append("top_two_margin")
                if float(acceptance_policy.get("max_entropy", 1.0)) < float(acceptance["entropy"][0]):
                    abstain_reasons.append("entropy")
            side = "flat"

        diagnostics = {
            "trained_at": payload["meta"].get("trained_at"),
            "training_rows": payload["meta"].get("training_rows"),
            "validation_accuracy": payload["meta"].get("validation_accuracy"),
            "validation_macro_f1": payload["meta"].get("validation_macro_f1"),
            "validation_brier": payload["meta"].get("validation_brier"),
            "validation_log_loss": payload["meta"].get("validation_log_loss"),
            "validation_ece": payload["meta"].get("validation_ece"),
            "walk_forward": payload["meta"].get("walk_forward", {}),
            "regime": regime_label,
            "regime_state_id": regime_state_id,
            "regime_confidence": round(regime_confidence, 4),
            "prob_short": round(float(calibrated_probabilities[0][0]), 4),
            "prob_flat": round(float(calibrated_probabilities[0][1]), 4),
            "prob_long": round(float(calibrated_probabilities[0][2]), 4),
            "raw_prob_short": round(float(raw_probabilities[0][0]), 4),
            "raw_prob_flat": round(float(raw_probabilities[0][1]), 4),
            "raw_prob_long": round(float(raw_probabilities[0][2]), 4),
            "prob_short_lgbm": round(float(lgbm_probs[0][0]), 4),
            "prob_flat_lgbm": round(float(lgbm_probs[0][1]), 4),
            "prob_long_lgbm": round(float(lgbm_probs[0][2]), 4),
            "prob_short_linear": round(float(linear_probs[0][0]), 4),
            "prob_flat_linear": round(float(linear_probs[0][1]), 4),
            "prob_long_linear": round(float(linear_probs[0][2]), 4),
            "blend_weight_lgbm": round(blend_weight, 4),
            "trade_quality_probability": round(meta_probability, 4),
            "probability_calibration_mode": probability_calibration_mode,
            "flat_class_post_calibration_metrics": payload["meta"].get("flat_class_post_calibration_metrics", {}),
            "acceptance_policy": {
                "mode": acceptance_policy.get("mode", "threshold_filters"),
                "min_top_probability": round(float(acceptance_policy.get("min_top_probability", 0.0)), 4),
                "min_margin": round(float(acceptance_policy.get("min_margin", 0.0)), 4),
                "max_entropy": round(float(acceptance_policy.get("max_entropy", 1.0)), 4),
                "min_score": round(float(acceptance_policy.get("min_score", 0.0)), 4),
                "regime_min_scores": {
                    str(label): round(float(value), 4)
                    for label, value in dict(acceptance_policy.get("regime_min_scores") or {}).items()
                },
                "target_coverage": round(float(acceptance_policy.get("target_coverage", 0.0)), 4),
                "achieved_coverage": round(float(acceptance_policy.get("achieved_coverage", 0.0)), 4),
                "achieved_precision": round(float(acceptance_policy.get("achieved_precision", 0.0)), 4),
            },
            "acceptance_score": round(float(acceptance["score"][0]) if len(acceptance["score"]) else 0.0, 4),
            "abstain_state": "accepted" if accepted else "abstain",
            "abstain_reasons": abstain_reasons,
            "proposed_side": proposed_side,
            "latest_price": round(float(prepared.close[latest_idx]), 6),
            "source": "direct_artifact_provider",
        }
        return HorizonSignal(
            horizon=horizon,
            side=side,
            confidence=round(combined_confidence, 4),
            raw_probabilities={
                "short": round(float(raw_probabilities[0][0]), 4),
                "flat": round(float(raw_probabilities[0][1]), 4),
                "long": round(float(raw_probabilities[0][2]), 4),
            },
            calibrated_probabilities={
                "short": round(float(calibrated_probabilities[0][0]), 4),
                "flat": round(float(calibrated_probabilities[0][1]), 4),
                "long": round(float(calibrated_probabilities[0][2]), 4),
            },
            abstain_state="accepted" if accepted else "abstain",
            diagnostics=diagnostics,
        )

    def _cached_payload(self, coin: str, horizon: str) -> dict[str, Any]:
        cache_key = f"{coin}:{horizon}"
        if cache_key not in self._artifact_cache:
            self._artifact_cache[cache_key] = load_artifact_payload(
                self.artifact_root,
                coin=coin,
                horizon=horizon,
            )
        return self._artifact_cache[cache_key]

    def _flat_forecast(self, coin: str, *, reason: str) -> CoinForecast:
        return CoinForecast(
            coin=coin,
            horizons={
                horizon: HorizonSignal(horizon=horizon, side="flat", confidence=0.0, diagnostics={"reason": reason})
                for horizon in self.quant.forecast_horizons
            },
            diagnostics={"primary_horizon": PRIMARY_HORIZON, "source": "direct_artifact_provider"},
        )
