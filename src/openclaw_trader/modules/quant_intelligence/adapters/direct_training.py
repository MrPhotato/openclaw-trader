from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from ....config.loader import coerce_system_settings, load_coinbase_credentials, load_system_settings
from ....shared.integrations.coinbase import CoinbaseAdvancedClient
from ....shared.protocols import Candle
from ..features import (
    build_adaptive_move_thresholds,
    build_asset_indicator_columns,
    build_interaction_feature_columns,
    build_long_horizon_feature_columns,
    build_reference_feature_columns,
    build_supervised_dataset,
    combine_supervised_datasets,
    prepare_series,
)
from ..support import (
    apply_flat_isotonic_rescale,
    apply_dirichlet_calibration,
    build_calibration_report_payload,
    build_daily_macro_feature_provider,
    build_high_confidence_policy,
    build_meta_features,
    build_meta_labels,
    build_snapshot_feature_provider,
    build_time_context_columns,
    blend_probabilities,
    calibrate_execution_policy,
    evaluate_high_confidence_policy,
    fetch_candles,
    fit_base_models_with_weights,
    fit_dirichlet_calibrator,
    fit_flat_isotonic_calibrator,
    fit_meta_calibrator,
    fit_meta_model,
    fit_regime_model,
    precision_at_fixed_coverages,
    predict_meta_probability,
    prediction_metrics,
    render_calibration_report_markdown,
    resolve_blend_weight,
    save_training_payload,
    search_acceptance_score_weights,
    summarize_flat_post_calibration,
    summarize_regime_metrics,
    walk_forward_predictions,
)
from ..support.snapshot_history import SnapshotFeatureProvider
from ..support.daily_macro_history import DailyMacroFeatureProvider


MODEL_ARTIFACT_VERSION = 5
PRIMARY_HORIZON = "1h"


class DirectQuantTrainer:
    def __init__(
        self,
        *,
        client: CoinbaseAdvancedClient | None = None,
        runtime: Any | None = None,
        artifact_root: Path | None = None,
        snapshot_feature_provider: SnapshotFeatureProvider | None = None,
        daily_macro_feature_provider: DailyMacroFeatureProvider | None = None,
    ) -> None:
        self.settings = load_system_settings() if runtime is None else coerce_system_settings(runtime)
        self.quant = self.settings.quant
        self.execution = self.settings.execution
        self.client = client or CoinbaseAdvancedClient(
            self.settings.coinbase or load_coinbase_credentials(self.settings.runtime_root)
        )
        self.artifact_root = artifact_root or (self.settings.paths.model_dir / "perps")
        self.candle_cache_dir = self.settings.paths.data_dir / "quant_candle_cache"
        self.snapshot_cache_dir = self.settings.paths.data_dir / "quant_snapshot_cache"
        self.candle_now: datetime | None = None
        self.snapshot_feature_provider = snapshot_feature_provider or build_snapshot_feature_provider(
            self.quant,
            cache_dir=self.snapshot_cache_dir,
        )
        self.daily_macro_feature_provider = daily_macro_feature_provider or build_daily_macro_feature_provider(
            self.quant,
            cache_dir=self.snapshot_cache_dir,
        )

    def retrain(self, coins: list[str] | None = None) -> dict[str, dict]:
        target_coins = [coin.upper() for coin in (coins or list(self.execution.supported_coins))]
        payload: dict[str, dict[str, Any]] = {
            coin: {"coin": coin, "primary_horizon": PRIMARY_HORIZON, "horizons": {}}
            for coin in target_coins
        }
        for horizon in self.quant.forecast_horizons:
            horizon_payloads = self.train_panel_horizon(target_coins, horizon=horizon)
            for coin, artifact in horizon_payloads.items():
                payload[coin]["horizons"][horizon] = artifact["meta"]
        return payload

    def train_all_horizons(self, coin: str) -> dict[str, Any]:
        return self.retrain([coin])[coin.upper()]

    def train_models(self, coin: str, *, horizon: str) -> dict[str, Any]:
        return self.train_panel_horizon([coin], horizon=horizon)[coin.upper()]

    @staticmethod
    def _coin_horizon_key(coin: str, horizon: str) -> str:
        return f"{coin.upper()}:{str(horizon).strip().lower()}"

    def _history_bars_for(self, coin: str, horizon: str) -> int:
        key = self._coin_horizon_key(coin, horizon)
        return int(
            self.quant.training_history_bars_overrides_by_coin_horizon.get(
                key,
                self.quant.training_history_bars_by_horizon.get(horizon, self.quant.history_bars),
            )
        )

    def _target_move_threshold_for(self, coin: str, horizon: str) -> float:
        key = self._coin_horizon_key(coin, horizon)
        return float(
            self.quant.target_move_threshold_pct_overrides_by_coin_horizon.get(
                key,
                self.quant.target_move_threshold_pct,
            )
        )

    def _probability_calibration_mode_for(self, coin: str, horizon: str) -> str:
        key = self._coin_horizon_key(coin, horizon)
        return str(
            self.quant.probability_calibration_mode_by_coin_horizon.get(
                key,
                "dirichlet",
            )
        ).strip().lower()

    def _global_acceptance_score_components_for(self, horizon: str) -> list[str]:
        return list(self.quant.acceptance_score_components_by_horizon.get(str(horizon).strip().lower(), []))

    def _acceptance_score_components_for(self, coin: str, horizon: str) -> list[str]:
        override_weights = self._acceptance_score_weights_override_for(coin, horizon)
        if override_weights:
            ordered = [name for name, weight in override_weights.items() if float(weight) > 0.0]
            if ordered:
                return ordered
            return list(override_weights.keys())
        return self._global_acceptance_score_components_for(horizon)

    def _acceptance_score_weights_override_for(self, coin: str, horizon: str) -> dict[str, float]:
        return dict(self.quant.acceptance_score_weights_by_coin_horizon.get(self._coin_horizon_key(coin, horizon), {}))

    def _regime_coverage_caps_for(self, coin: str, horizon: str) -> dict[str, float]:
        return dict(self.quant.regime_coverage_caps_by_coin_horizon.get(self._coin_horizon_key(coin, horizon), {}))

    def _specialist_enabled_for(self, coin: str, horizon: str) -> bool:
        return bool(
            str(horizon).strip() in set(self.quant.specialist_horizons)
            or self._coin_horizon_key(coin, horizon) in set(self.quant.specialist_coin_horizons)
        )

    def train_panel_horizon(self, coins: list[str], *, horizon: str) -> dict[str, Any]:
        target_coins = [coin.upper() for coin in coins]
        horizon_bars = int(self.quant.forecast_horizons[horizon])
        lookback_bars_by_coin = {coin: self._history_bars_for(coin, horizon) for coin in target_coins}
        max_reference_lookback = max(
            [lookback_bars_by_coin.get(coin, self.quant.history_bars) for coin in target_coins if coin != "BTC"],
            default=lookback_bars_by_coin.get("BTC", self.quant.history_bars),
        )
        candle_cache = {
            coin: fetch_candles(
                self.client,
                coin=coin,
                quant=self.quant,
                lookback_bars=lookback_bars_by_coin[coin],
                cache_dir=self.candle_cache_dir,
                now=self.candle_now,
            )
            for coin in target_coins
        }
        btc_reference_candles = candle_cache.get("BTC")
        if any(coin != "BTC" for coin in target_coins) and (
            btc_reference_candles is None or len(btc_reference_candles) < max_reference_lookback
        ):
            btc_reference_candles = fetch_candles(
                self.client,
                coin="BTC",
                quant=self.quant,
                lookback_bars=max_reference_lookback,
                cache_dir=self.candle_cache_dir,
                now=self.candle_now,
            )

        coin_datasets: dict[str, Any] = {}
        regime_payloads: dict[str, dict[str, Any]] = {}
        snapshot_summaries: dict[str, dict[str, float]] = {}
        daily_macro_summaries: dict[str, dict[str, Any]] = {}
        threshold_diagnostics: dict[str, dict[str, float]] = {}
        daily_macro_feature_names: dict[str, list[str]] = {}
        for coin in target_coins:
            candles = candle_cache[coin]
            if len(candles) < self.quant.min_train_samples:
                raise ValueError(f"not enough candles to train model for {coin}: {len(candles)}")
            regime_payload = fit_regime_model(coin, candles, quant=self.quant)
            regime_payloads[coin] = regime_payload
            extra_columns, sample_weights, snapshot_summary, daily_macro_summary, slow_feature_names = self._build_extra_feature_columns(
                coin,
                candles,
                reference_candles=btc_reference_candles,
                horizon=horizon,
            )
            extra_columns["regime_state"] = regime_payload["state_sequence"]
            extra_columns["regime_confidence"] = regime_payload["state_confidence"]
            prepared = prepare_series(candles, self.quant.feature_windows)
            move_threshold_pct = self._target_move_threshold_for(coin, horizon)
            adaptive_thresholds = None
            threshold_summary = {
                "mode": "fixed",
                "base_threshold_pct": round(float(self.quant.target_move_threshold_pct), 6),
                "applied_threshold_pct": round(float(move_threshold_pct), 6),
                "threshold_source": (
                    "coin_horizon_override"
                    if self._coin_horizon_key(coin, horizon) in self.quant.target_move_threshold_pct_overrides_by_coin_horizon
                    else "global_default"
                ),
            }
            if self.quant.adaptive_labeling_enabled:
                adaptive_thresholds, threshold_stats = build_adaptive_move_thresholds(
                    prepared,
                    base_threshold_pct=move_threshold_pct,
                    horizon_bars=horizon_bars,
                    volatility_window=self.quant.label_volatility_window_by_horizon.get(horizon, 48),
                    floor_multiplier=self.quant.label_threshold_floor_multiplier_by_horizon.get(horizon, 0.5),
                    cap_multiplier=self.quant.label_threshold_cap_multiplier_by_horizon.get(horizon, 3.0),
                )
                threshold_summary = {
                    "mode": "volatility_normalized",
                    "base_threshold_pct": round(float(self.quant.target_move_threshold_pct), 6),
                    "applied_threshold_pct": round(float(move_threshold_pct), 6),
                    "threshold_source": (
                        "coin_horizon_override"
                        if self._coin_horizon_key(coin, horizon) in self.quant.target_move_threshold_pct_overrides_by_coin_horizon
                        else "global_default"
                    ),
                    "volatility_window": int(self.quant.label_volatility_window_by_horizon.get(horizon, 48)),
                    **threshold_stats,
                }
            dataset = build_supervised_dataset(
                candles,
                windows=self.quant.feature_windows,
                horizon_bars=horizon_bars,
                move_threshold_pct=move_threshold_pct,
                move_thresholds=adaptive_thresholds,
                round_trip_cost_pct=self.quant.round_trip_cost_pct,
                extra_columns=extra_columns,
                row_weights=sample_weights,
                coin_label=coin,
                regime_state_map=regime_payload["state_map"],
            )
            if len(dataset.x) < self.quant.min_train_samples:
                raise ValueError(f"not enough supervised samples to train model for {coin}: {len(dataset.x)}")
            coin_datasets[coin] = dataset
            snapshot_summaries[coin] = snapshot_summary
            daily_macro_summaries[coin] = daily_macro_summary
            threshold_diagnostics[coin] = threshold_summary
            daily_macro_feature_names[coin] = slow_feature_names

        panel_dataset = combine_supervised_datasets(coin_datasets)
        if len(panel_dataset.x) < self.quant.min_train_samples:
            raise ValueError(f"not enough supervised samples to train panel for {','.join(target_coins)}")

        walk_forward = walk_forward_predictions(
            panel_dataset,
            quant=self.quant,
            regime_state_map={},
            horizon_bars=horizon_bars,
        )
        if walk_forward["count"] == 0:
            raise ValueError(f"walk-forward evaluation did not produce any holdout rows for {','.join(target_coins)}")

        panel_blend_weight = resolve_blend_weight(walk_forward["metrics"])
        base_models = fit_base_models_with_weights(
            panel_dataset.x,
            panel_dataset.y,
            quant=self.quant,
            sample_weight=panel_dataset.sample_weights,
        )
        feature_names = panel_dataset.feature_names
        reference_features = sorted(name for name in feature_names if name.startswith(("btc_", "rel_")))
        time_context_features = sorted(name for name in feature_names if name.startswith("time_") and "_x_" not in name)
        market_snapshot_features = sorted(name for name in feature_names if name.startswith("market_") and "_x_" not in name)
        interaction_features = sorted(name for name in feature_names if name.startswith("jump_") or "_x_" in name)
        global_ranking_components = self._global_acceptance_score_components_for(horizon)

        specialist_oof: dict[str, dict[str, Any]] = {}
        if len(target_coins) > 1 and any(self._specialist_enabled_for(coin, horizon) for coin in target_coins):
            panel_time_windows = walk_forward.get("time_windows", [])
            for coin in target_coins:
                if not self._specialist_enabled_for(coin, horizon):
                    continue
                specialist_walk_forward = walk_forward_predictions(
                    coin_datasets[coin],
                    quant=self.quant,
                    regime_state_map=regime_payloads[coin]["state_map"],
                    horizon_bars=horizon_bars,
                    time_windows=panel_time_windows,
                )
                if specialist_walk_forward["count"] == 0:
                    continue
                specialist_base_models = fit_base_models_with_weights(
                    coin_datasets[coin].x,
                    coin_datasets[coin].y,
                    quant=self.quant,
                    sample_weight=coin_datasets[coin].sample_weights,
                )
                specialist_blend_weight = resolve_blend_weight(specialist_walk_forward["metrics"])
                specialist_oof[coin] = {
                    "base_models": specialist_base_models,
                    "walk_forward": specialist_walk_forward,
                    "blend_weight": specialist_blend_weight,
                    "blended_probs": blend_probabilities(
                        specialist_walk_forward["lgbm_probs"],
                        specialist_walk_forward["linear_probs"],
                        lgbm_weight=specialist_blend_weight,
                    ),
                }

        coin_states: dict[str, dict[str, Any]] = {}
        for coin in target_coins:
            coin_mask = walk_forward["coin_labels"] == coin
            if not np.any(coin_mask):
                raise ValueError(f"panel walk-forward produced no OOF rows for {coin}")
            coin_y = walk_forward["y"][coin_mask]
            coin_lgbm_probs = walk_forward["lgbm_probs"][coin_mask]
            coin_linear_probs = walk_forward["linear_probs"][coin_mask]
            coin_net_long_returns = walk_forward["net_long_returns"][coin_mask]
            coin_net_short_returns = walk_forward["net_short_returns"][coin_mask]
            coin_regime_labels = walk_forward["regime_labels"][coin_mask]
            coin_walk_forward_metrics = {
                "lgbm": prediction_metrics(coin_y, coin_lgbm_probs, coin_net_long_returns, coin_net_short_returns),
                "linear": prediction_metrics(coin_y, coin_linear_probs, coin_net_long_returns, coin_net_short_returns),
            }
            coin_blend_weight = resolve_blend_weight(coin_walk_forward_metrics)
            coin_blended_probs = blend_probabilities(
                coin_lgbm_probs,
                coin_linear_probs,
                lgbm_weight=coin_blend_weight,
            )
            specialist_summary: dict[str, Any] = {"enabled": False}
            specialist_bundle = specialist_oof.get(coin)
            if specialist_bundle is not None:
                aligned_specialist_probs = self._align_probabilities_by_keys(
                    target_timestamps=walk_forward["timestamps"][coin_mask],
                    target_indices=walk_forward["indices"][coin_mask],
                    source_timestamps=specialist_bundle["walk_forward"]["timestamps"],
                    source_indices=specialist_bundle["walk_forward"]["indices"],
                    source_probabilities=specialist_bundle["blended_probs"],
                    fallback_probabilities=coin_blended_probs,
                )
                specialist_weight = self._resolve_specialist_weight(
                    y_true=coin_y,
                    panel_probabilities=coin_blended_probs,
                    specialist_probabilities=aligned_specialist_probs,
                    net_long_returns=coin_net_long_returns,
                    net_short_returns=coin_net_short_returns,
                )
                coin_blended_probs = blend_probabilities(
                    aligned_specialist_probs,
                    coin_blended_probs,
                    lgbm_weight=specialist_weight,
                )
                specialist_summary = {
                    "enabled": True,
                    "blend_weight": round(float(specialist_weight), 4),
                    "base_blend_weight": round(float(specialist_bundle["blend_weight"]), 4),
                    "training_rows": int(len(coin_datasets[coin].x)),
                }

            probability_calibration_mode = self._probability_calibration_mode_for(coin, horizon)
            dirichlet_calibrator = fit_dirichlet_calibrator(
                coin_blended_probs,
                coin_y,
                random_seed=self.quant.random_seed,
            )
            dirichlet_calibrated_oof = apply_dirichlet_calibration(dirichlet_calibrator, coin_blended_probs)
            flat_class_calibrator = None
            calibrated_oof = dirichlet_calibrated_oof
            if probability_calibration_mode == "flat_isotonic_rescale":
                flat_class_calibrator = fit_flat_isotonic_calibrator(
                    dirichlet_calibrated_oof,
                    coin_y,
                )
                calibrated_oof = apply_flat_isotonic_rescale(
                    flat_class_calibrator,
                    dirichlet_calibrated_oof,
                )
            classwise_ece_before_post_calibration = prediction_metrics(
                coin_y,
                dirichlet_calibrated_oof,
                coin_net_long_returns,
                coin_net_short_returns,
            )["classwise_ece"]
            classwise_ece_after_post_calibration = prediction_metrics(
                coin_y,
                calibrated_oof,
                coin_net_long_returns,
                coin_net_short_returns,
            )["classwise_ece"]
            flat_class_post_calibration_metrics = summarize_flat_post_calibration(
                coin_y,
                dirichlet_calibrated_oof,
                calibrated_oof,
                active=probability_calibration_mode == "flat_isotonic_rescale",
            )
            meta_features_oof = build_meta_features(calibrated_oof)
            meta_labels_oof = build_meta_labels(
                calibrated_oof,
                coin_net_long_returns,
                coin_net_short_returns,
            )
            meta_model = fit_meta_model(
                meta_features_oof,
                meta_labels_oof,
                random_seed=self.quant.random_seed,
            )
            meta_calibrator = fit_meta_calibrator(meta_model, meta_features_oof, meta_labels_oof)
            oof_trade_quality = predict_meta_probability(meta_model, meta_calibrator, meta_features_oof)
            coin_states[coin] = {
                "y": coin_y,
                "calibrated_oof": calibrated_oof,
                "trade_quality": oof_trade_quality,
                "net_long_returns": coin_net_long_returns,
                "net_short_returns": coin_net_short_returns,
                "regime_labels": coin_regime_labels,
                "blended_metrics": prediction_metrics(
                    coin_y,
                    calibrated_oof,
                    coin_net_long_returns,
                    coin_net_short_returns,
                    trade_quality=oof_trade_quality,
                ),
                "raw_metrics": prediction_metrics(
                    coin_y,
                    coin_blended_probs,
                    coin_net_long_returns,
                    coin_net_short_returns,
                ),
                "coin_blend_weight": coin_blend_weight,
                "specialist_summary": specialist_summary,
                "specialist_base_models": specialist_bundle["base_models"] if specialist_bundle is not None else None,
                "probability_calibration_mode": probability_calibration_mode,
                "dirichlet_calibrator": dirichlet_calibrator,
                "flat_class_calibrator": flat_class_calibrator,
                "meta_model": meta_model,
                "meta_calibrator": meta_calibrator,
                "meta_positive_rate": round(float(meta_labels_oof.mean()) if len(meta_labels_oof) else 0.0, 4),
                "classwise_ece_before_post_calibration": classwise_ece_before_post_calibration,
                "classwise_ece_after_post_calibration": classwise_ece_after_post_calibration,
                "flat_class_post_calibration_metrics": flat_class_post_calibration_metrics,
            }

        global_score_weights: dict[str, float] = {}
        global_score_metrics: dict[str, Any] = {}
        if global_ranking_components:
            stacked_probs = np.vstack([coin_states[coin]["calibrated_oof"] for coin in target_coins])
            stacked_y = np.concatenate([coin_states[coin]["y"] for coin in target_coins], axis=0)
            stacked_net_long = np.concatenate([coin_states[coin]["net_long_returns"] for coin in target_coins], axis=0)
            stacked_net_short = np.concatenate([coin_states[coin]["net_short_returns"] for coin in target_coins], axis=0)
            stacked_trade_quality = np.concatenate([coin_states[coin]["trade_quality"] for coin in target_coins], axis=0)
            global_score_weights, global_score_metrics = search_acceptance_score_weights(
                stacked_probs,
                stacked_y,
                stacked_net_long,
                stacked_net_short,
                components=global_ranking_components,
                target_coverage=self.quant.high_confidence_target_coverage,
                trade_quality=stacked_trade_quality,
            )

        results: dict[str, Any] = {}
        for coin in target_coins:
            coin_state = coin_states[coin]
            coin_y = coin_state["y"]
            calibrated_oof = coin_state["calibrated_oof"]
            oof_trade_quality = coin_state["trade_quality"]
            coin_net_long_returns = coin_state["net_long_returns"]
            coin_net_short_returns = coin_state["net_short_returns"]
            coin_regime_labels = coin_state["regime_labels"]
            blended_metrics = coin_state["blended_metrics"]
            raw_metrics = coin_state["raw_metrics"]
            coin_blend_weight = float(coin_state["coin_blend_weight"])
            regime_coverage_caps = self._regime_coverage_caps_for(coin, horizon)
            acceptance_score_weights = self._acceptance_score_weights_override_for(coin, horizon)
            coin_ranking_components = self._acceptance_score_components_for(coin, horizon)
            acceptance_score_metrics: dict[str, Any] = {}
            acceptance_score_mode = "top_probability_rank"
            if coin_ranking_components:
                acceptance_score_mode = "score_rank"
                if acceptance_score_weights:
                    acceptance_score_metrics = {"optimized_on": "config_override"}
                elif regime_coverage_caps:
                    acceptance_score_weights, acceptance_score_metrics = search_acceptance_score_weights(
                        calibrated_oof,
                        coin_y,
                        coin_net_long_returns,
                        coin_net_short_returns,
                        components=coin_ranking_components,
                        target_coverage=self.quant.high_confidence_target_coverage,
                        trade_quality=oof_trade_quality,
                        regime_labels=coin_regime_labels,
                        regime_coverage_caps=regime_coverage_caps,
                        seeded_weights=global_score_weights or None,
                    )
                    acceptance_score_metrics["optimized_on"] = "coin_horizon"
                else:
                    acceptance_score_weights = dict(global_score_weights)
                    acceptance_score_metrics = {"optimized_on": "global_panel", **dict(global_score_metrics)}

            calibrated_policy = calibrate_execution_policy(
                quant=self.quant,
                probabilities=calibrated_oof,
                trade_quality=oof_trade_quality,
                net_long_returns=coin_net_long_returns,
                net_short_returns=coin_net_short_returns,
                regime_labels=coin_regime_labels,
            )
            acceptance_policy = build_high_confidence_policy(
                calibrated_oof,
                coin_y,
                target_coverage=self.quant.high_confidence_target_coverage,
                trade_quality=oof_trade_quality,
                regime_labels=coin_regime_labels,
                score_components=coin_ranking_components,
                score_weights=acceptance_score_weights or None,
                regime_coverage_caps=regime_coverage_caps,
            )
            high_confidence_metrics = precision_at_fixed_coverages(
                coin_y,
                calibrated_oof,
                coin_net_long_returns,
                coin_net_short_returns,
                trade_quality=oof_trade_quality,
                ranking_components=coin_ranking_components,
                ranking_weights=acceptance_score_weights or None,
                regime_labels=coin_regime_labels,
                regime_coverage_caps=regime_coverage_caps,
            )
            target_acceptance = evaluate_high_confidence_policy(
                calibrated_oof,
                acceptance_policy,
                trade_quality=oof_trade_quality,
                regime_labels=coin_regime_labels,
            )
            accepted_mask = np.asarray(target_acceptance["accepted"], dtype=bool)
            prediction = np.argmax(calibrated_oof, axis=1)
            realized_returns = np.zeros(len(prediction), dtype=np.float64)
            realized_returns[prediction == 0] = coin_net_short_returns[prediction == 0]
            realized_returns[prediction == 2] = coin_net_long_returns[prediction == 2]
            accepted_trade_mask = accepted_mask & (prediction != 1)
            regime_metrics = summarize_regime_metrics(
                coin_y,
                calibrated_oof,
                coin_regime_labels,
                coin_net_long_returns,
                coin_net_short_returns,
                accepted_mask=accepted_mask,
            )
            if coin_ranking_components and "precision" not in acceptance_score_metrics:
                target_bucket = high_confidence_metrics.get("30%", {})
                acceptance_score_metrics.update(
                    {
                        "precision": round(float(target_bucket.get("precision", 0.0)), 4),
                        "trade_precision": round(float(target_bucket.get("trade_precision", 0.0)), 4),
                        "coverage": round(float(target_bucket.get("achieved_coverage", 0.0)), 4),
                        "avg_net_return": round(float(target_bucket.get("avg_net_return", 0.0)), 6),
                    }
                )

            payload = {
                "meta": {
                    "artifact_version": MODEL_ARTIFACT_VERSION,
                    "coin": coin.upper(),
                    "horizon": horizon,
                    "trained_at": datetime.now(UTC).isoformat(),
                    "feature_names": feature_names,
                    "training_scope": "panel",
                    "panel_coins": list(target_coins),
                    "training_rows": int(len(panel_dataset.x)),
                    "panel_training_rows": int(len(panel_dataset.x)),
                    "coin_training_rows": int(len(coin_datasets[coin].x)),
                    "interval": self.quant.interval,
                    "history_bars": lookback_bars_by_coin[coin],
                    "forecast_horizon_bars": horizon_bars,
                    "move_threshold_pct": self.quant.target_move_threshold_pct,
                    "label_threshold_pct": threshold_diagnostics[coin]["applied_threshold_pct"],
                    "threshold_diagnostics": threshold_diagnostics[coin],
                    "round_trip_cost_pct": self.quant.round_trip_cost_pct,
                    "regime_state_map": regime_payloads[coin]["state_map"],
                    "reference_features": reference_features,
                    "time_context_features": time_context_features,
                    "market_snapshot_features": market_snapshot_features,
                    "interaction_features": interaction_features,
                    "label_diagnostics": self._build_label_diagnostics(coin_datasets[coin], coin_y, accepted_mask),
                    "probability_calibration_mode": coin_state["probability_calibration_mode"],
                    "blend_weight_lgbm": round(coin_blend_weight, 4),
                    "panel_blend_weight_lgbm": round(panel_blend_weight, 4),
                    "specialist_summary": coin_state["specialist_summary"],
                    "validation_accuracy": blended_metrics["accuracy"],
                    "validation_macro_f1": blended_metrics["macro_f1"],
                    "validation_brier": blended_metrics["brier"],
                    "validation_log_loss": blended_metrics["log_loss"],
                    "validation_ece": blended_metrics["ece"],
                    "validation_classwise_ece": blended_metrics["classwise_ece"],
                    "classwise_ece_before_post_calibration": coin_state["classwise_ece_before_post_calibration"],
                    "classwise_ece_after_post_calibration": coin_state["classwise_ece_after_post_calibration"],
                    "flat_class_post_calibration_metrics": coin_state["flat_class_post_calibration_metrics"],
                    "raw_validation_accuracy": raw_metrics["accuracy"],
                    "raw_validation_macro_f1": raw_metrics["macro_f1"],
                    "calibrated_policy": calibrated_policy,
                    "acceptance_policy": acceptance_policy,
                    "acceptance_score_mode": acceptance_score_mode,
                    "acceptance_score_weights": acceptance_score_weights,
                    "acceptance_score_metrics": acceptance_score_metrics,
                    "regime_acceptance_policy": {
                        "active": bool(regime_coverage_caps),
                        "coverage_caps": regime_coverage_caps,
                        "regime_min_scores": dict(acceptance_policy.get("regime_min_scores") or {}),
                    },
                    "snapshot_quality": snapshot_summaries[coin],
                    "data_source_coverage": snapshot_summaries[coin],
                    "daily_feature_coverage": daily_macro_summaries[coin].get("daily_feature_coverage", {}),
                    "coinalyze_enabled": daily_macro_summaries[coin].get("coinalyze_enabled", False),
                    "coinalyze_history_summary": daily_macro_summaries[coin].get("coinalyze_history_summary", {}),
                    "tardis_monthly_anchor_summary": daily_macro_summaries[coin].get("tardis_monthly_anchor_summary", {}),
                    "feature_family_summary": {
                        "reference": len(reference_features),
                        "time_context": len(time_context_features),
                        "snapshot": len(market_snapshot_features),
                        "interaction": len(interaction_features),
                        "daily_macro": len(daily_macro_feature_names[coin]),
                    },
                    "12h_feature_family_summary": {
                        "daily_macro_features": daily_macro_feature_names[coin],
                        "enabled": bool(daily_macro_feature_names[coin]),
                    },
                    "high_confidence_metrics": {
                        "metric": acceptance_score_mode,
                        "precision_at_coverage": high_confidence_metrics,
                        "target_policy": {
                            "target_coverage": round(float(acceptance_policy.get("target_coverage", 0.0)), 4),
                            "achieved_coverage": round(float(target_acceptance.get("coverage", 0.0)), 4),
                            "precision": round(
                                float(np.mean(prediction[accepted_mask] == coin_y[accepted_mask])) if np.any(accepted_mask) else 0.0,
                                4,
                            ),
                            "trade_precision": round(
                                float(np.mean(realized_returns[accepted_trade_mask] > 0)) if np.any(accepted_trade_mask) else 0.0,
                                4,
                            ),
                            "trade_coverage": round(float(np.mean(accepted_trade_mask)) if len(accepted_trade_mask) else 0.0, 4),
                            "avg_net_return": round(
                                float(np.mean(realized_returns[accepted_trade_mask])) if np.any(accepted_trade_mask) else 0.0,
                                6,
                            ),
                            "avg_score": round(
                                float(np.mean(np.asarray(target_acceptance.get("score", np.zeros(len(accepted_mask))))[accepted_mask]))
                                if np.any(accepted_mask)
                                else 0.0,
                                6,
                            ),
                        },
                    },
                    "regime_metrics": regime_metrics,
                    "walk_forward": {
                        **walk_forward["summary"],
                        "blend_weight_lgbm": round(coin_blend_weight, 4),
                        "panel_blend_weight_lgbm": round(panel_blend_weight, 4),
                        "coin_rows": int(np.sum(walk_forward["coin_labels"] == coin)),
                        "meta_positive_rate": coin_state["meta_positive_rate"],
                    },
                    "global_acceptance_score_weights": global_score_weights,
                    "global_acceptance_score_metrics": global_score_metrics,
                },
                "regime": regime_payloads[coin],
                "classifier": {
                    "base_models": base_models,
                    "specialist_base_models": coin_state["specialist_base_models"],
                    "dirichlet_calibrator": coin_state["dirichlet_calibrator"],
                    "flat_class_calibrator": coin_state["flat_class_calibrator"],
                    "meta_model": coin_state["meta_model"],
                    "meta_calibrator": coin_state["meta_calibrator"],
                },
            }
            report_payload = build_calibration_report_payload(payload["meta"], quant=self.quant)
            report_markdown = render_calibration_report_markdown(report_payload)
            results[coin] = save_training_payload(
                self.artifact_root,
                coin=coin,
                horizon=horizon,
                payload=payload,
                report_payload=report_payload,
                report_markdown=report_markdown,
            )
        return results

    def _build_extra_feature_columns(
        self,
        coin: str,
        candles: list[Candle],
        *,
        reference_candles: list[Candle] | None = None,
        horizon: str,
    ) -> tuple[dict[str, Any], Any, dict[str, float], dict[str, Any], list[str]]:
        primary = prepare_series(candles, self.quant.feature_windows)
        extra_columns = dict(build_time_context_columns(candles))
        extra_columns.update(build_long_horizon_feature_columns(primary))
        aligned_reference: list[Candle] | None = None
        if coin.upper() != "BTC":
            btc_reference = reference_candles or fetch_candles(
                self.client,
                coin="BTC",
                quant=self.quant,
                cache_dir=self.candle_cache_dir,
                now=self.candle_now,
            )
            aligned_reference = self._align_reference_candles(candles, btc_reference)
            if aligned_reference is not None and len(aligned_reference) == len(candles):
                reference = prepare_series(aligned_reference, self.quant.feature_windows)
                extra_columns.update(build_reference_feature_columns(primary, reference, prefix="btc"))
        snapshot_payload = self.snapshot_feature_provider.build_feature_payload(
            coin=coin,
            candles=candles,
            quant=self.quant,
        )
        extra_columns.update(snapshot_payload.columns)
        daily_macro_summary: dict[str, Any] = {}
        daily_macro_feature_names: list[str] = []
        if str(horizon).strip().lower() == "12h":
            daily_macro_payload = self.daily_macro_feature_provider.build_feature_payload(
                coin=coin,
                candles=candles,
                quant=self.quant,
            )
            extra_columns.update(daily_macro_payload.columns)
            daily_macro_summary = dict(daily_macro_payload.quality_summary or {})
            daily_macro_feature_names = sorted(daily_macro_payload.columns.keys())
        if coin.upper() != "BTC" and aligned_reference is not None and len(aligned_reference) == len(candles):
            btc_snapshot_payload = self.snapshot_feature_provider.build_feature_payload(
                coin="BTC",
                candles=aligned_reference,
                quant=self.quant,
            )
            extra_columns.update(
                self._build_snapshot_reference_columns(
                    primary_columns=snapshot_payload.columns,
                    reference_columns=btc_snapshot_payload.columns,
                    prefix="btc",
                )
            )
        extra_columns.update(build_asset_indicator_columns(coin=coin, length=len(candles)))
        interaction_source = dict(primary.features)
        interaction_source.update(extra_columns)
        extra_columns.update(build_interaction_feature_columns(primary, interaction_source))
        return (
            extra_columns,
            snapshot_payload.sample_weights,
            (snapshot_payload.quality_summary or {}),
            daily_macro_summary,
            daily_macro_feature_names,
        )

    @staticmethod
    def _align_reference_candles(
        target_candles: list[Candle],
        reference_candles: list[Candle],
    ) -> list[Candle] | None:
        if len(target_candles) == len(reference_candles):
            return reference_candles
        lookup = {int(candle.start): candle for candle in reference_candles}
        aligned = [lookup.get(int(candle.start)) for candle in target_candles]
        if any(candle is None for candle in aligned):
            return None
        return [candle for candle in aligned if candle is not None]

    @staticmethod
    def _build_snapshot_reference_columns(
        *,
        primary_columns: dict[str, Any],
        reference_columns: dict[str, Any],
        prefix: str = "btc",
    ) -> dict[str, Any]:
        features: dict[str, Any] = {}
        feature_names = (
            "market_funding_rate",
            "market_premium",
            "market_open_interest_change_24",
            "market_open_interest_change_96",
            "market_open_interest_change_192",
            "market_open_interest_change_384",
            "market_day_volume_change_24",
            "market_day_volume_change_96",
            "market_day_volume_change_192",
            "market_day_volume_change_384",
            "market_funding_change_96",
            "market_funding_change_384",
            "market_premium_change_96",
            "market_premium_change_384",
        )
        for name in feature_names:
            primary = primary_columns.get(name)
            reference = reference_columns.get(name)
            if primary is None or reference is None:
                continue
            reference_array = np.asarray(reference, dtype=np.float64)
            primary_array = np.asarray(primary, dtype=np.float64)
            features[f"{prefix}_{name}"] = reference_array
            features[f"rel_{name}_vs_{prefix}"] = primary_array - reference_array
        return features

    @staticmethod
    def _align_probabilities_by_keys(
        *,
        target_timestamps: np.ndarray,
        target_indices: np.ndarray,
        source_timestamps: np.ndarray,
        source_indices: np.ndarray,
        source_probabilities: np.ndarray,
        fallback_probabilities: np.ndarray,
    ) -> np.ndarray:
        aligned = np.asarray(fallback_probabilities, dtype=np.float64).copy()
        lookup = {
            (int(timestamp), int(index)): source_probabilities[row_idx]
            for row_idx, (timestamp, index) in enumerate(zip(source_timestamps, source_indices))
        }
        for row_idx, key in enumerate(zip(target_timestamps, target_indices)):
            payload = lookup.get((int(key[0]), int(key[1])))
            if payload is not None:
                aligned[row_idx] = payload
        return aligned

    @staticmethod
    def _resolve_specialist_weight(
        *,
        y_true: np.ndarray,
        panel_probabilities: np.ndarray,
        specialist_probabilities: np.ndarray,
        net_long_returns: np.ndarray,
        net_short_returns: np.ndarray,
    ) -> float:
        candidates = (0.2, 0.35, 0.5, 0.65, 0.8)
        best_weight = 0.5
        best_score = float("-inf")
        for candidate in candidates:
            blended = blend_probabilities(
                specialist_probabilities,
                panel_probabilities,
                lgbm_weight=float(candidate),
            )
            metrics = precision_at_fixed_coverages(
                y_true,
                blended,
                net_long_returns,
                net_short_returns,
            ).get("30%", {})
            score = float(metrics.get("precision", 0.0))
            if score > best_score:
                best_score = score
                best_weight = float(candidate)
        return best_weight

    @staticmethod
    def _build_label_diagnostics(
        dataset: Any,
        y_true: np.ndarray,
        accepted_mask: np.ndarray,
    ) -> dict[str, Any]:
        label_names = {0: "short", 1: "flat", 2: "long"}
        distribution: dict[str, int] = {
            label_names[label]: int(np.sum(dataset.y == label))
            for label in (0, 1, 2)
        }
        by_regime: dict[str, dict[str, int]] = {}
        for regime_label in sorted(set(str(item) for item in dataset.regime_labels)):
            mask = np.asarray(dataset.regime_labels == regime_label)
            by_regime[regime_label] = {
                label_names[label]: int(np.sum(mask & (dataset.y == label)))
                for label in (0, 1, 2)
            }
        accepted_labels = y_true[accepted_mask]
        accepted_distribution = {
            label_names[label]: int(np.sum(accepted_labels == label))
            for label in (0, 1, 2)
        }
        accepted_total = max(int(len(accepted_labels)), 1)
        accepted_probs = np.asarray(
            [accepted_distribution[label_names[label]] / accepted_total for label in (0, 1, 2)],
            dtype=np.float64,
        )
        accepted_entropy = 0.0
        finite = accepted_probs > 0
        if np.any(finite):
            accepted_entropy = float(-np.sum(accepted_probs[finite] * np.log(accepted_probs[finite])) / np.log(3))
        return {
            "distribution": distribution,
            "distribution_by_regime": by_regime,
            "high_confidence_slice": {
                "rows": int(np.sum(accepted_mask)),
                "distribution": accepted_distribution,
                "normalized_entropy": round(accepted_entropy, 6),
            },
        }
