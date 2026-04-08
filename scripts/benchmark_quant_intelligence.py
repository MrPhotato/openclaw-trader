from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import textwrap
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import certifi
import httpx
import joblib

from openclaw_trader.config.models import (
    AgentSettings,
    BusSettings,
    ExecutionSettings,
    NotificationSettings,
    QuantSettings,
    StorageSettings,
    SystemSettings,
    WorkflowSettings,
)
from openclaw_trader.modules.quant_intelligence.adapters import DirectQuantTrainer
from openclaw_trader.modules.quant_intelligence.support import build_snapshot_feature_provider
from openclaw_trader.shared.protocols.market_types import Candle
from _quant_history_bundle import manifest_path as history_manifest_path
from _quant_history_bundle import prepare_history_bundle


COINS = ("BTC", "ETH", "SOL")
HORIZONS = ("4h", "12h")
COVERAGE_BUCKETS = ("20%", "30%", "40%")
BINANCE_SYMBOL_BY_COIN = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}
CURRENT_PROFILES = ("baseline_long_history",)
ETH4H_REGIME_CAPS = {"ETH:4h": {"bearish_breakdown": 0.08, "bullish_trend": 0.10, "neutral_consolidation": 0.16}}
ETH4H_ACCEPTANCE_SCORE_WEIGHTS = {"ETH:4h": {"meta_trade_quality_probability": 1.0}}
ETH4H_LABEL_THRESHOLD_CANDIDATES = (0.0020, 0.00225, 0.0025, 0.00275, 0.0030)
ETH4H_SIGNAL_THRESHOLD_CANDIDATES = (0.0025, 0.00275, 0.0030)


def build_snapshot_provider_from_settings(*, settings: SystemSettings, cache_dir: Path):
    return build_snapshot_feature_provider(settings.quant, cache_dir=cache_dir)


class PublicCoinbaseCandleClient:
    def __init__(self, *, timeout: float = 20.0) -> None:
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        self._client = httpx.Client(
            base_url="https://api.coinbase.com",
            timeout=timeout,
            verify=ssl_context,
            trust_env=False,
            headers={"User-Agent": "openclaw-trader/qi-benchmark"},
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


def build_benchmark_settings(
    runtime_root: Path,
    *,
    forecast_horizons: dict[str, int] | None = None,
    training_history_bars_overrides_by_coin_horizon: dict[str, int] | None = None,
    target_move_threshold_pct_overrides_by_coin_horizon: dict[str, float] | None = None,
    probability_calibration_mode_by_coin_horizon: dict[str, str] | None = None,
    acceptance_score_components_by_horizon: dict[str, list[str]] | None = None,
    acceptance_score_weights_by_coin_horizon: dict[str, dict[str, float]] | None = None,
    regime_coverage_caps_by_coin_horizon: dict[str, dict[str, float]] | None = None,
    specialist_coin_horizons: list[str] | None = None,
    daily_macro_features_enabled: bool = True,
    history_backfill_days: int = 540,
) -> SystemSettings:
    effective_horizons = dict(forecast_horizons or {"4h": 16, "12h": 48})
    primary_horizon_bars = int(effective_horizons.get("4h", next(iter(effective_horizons.values()))))
    quant_kwargs: dict[str, Any] = {
        "interval": "15m",
        "history_bars": 1500,
        "training_history_bars_by_horizon": {"1h": 1500, "4h": 12000, "12h": 48000},
        "training_history_bars_overrides_by_coin_horizon": training_history_bars_overrides_by_coin_horizon or {},
        "forecast_horizons": effective_horizons,
        "target_move_threshold_pct": 0.0025,
        "round_trip_cost_pct": 0.0012,
        "adaptive_labeling_enabled": False,
        "acceptance_score_components_by_horizon": acceptance_score_components_by_horizon or {},
        "acceptance_score_weights_by_coin_horizon": acceptance_score_weights_by_coin_horizon or {},
        "regime_coverage_caps_by_coin_horizon": regime_coverage_caps_by_coin_horizon or {},
        "specialist_horizons": [],
        "specialist_coin_horizons": specialist_coin_horizons or [],
        "retrain_after_minutes": 360,
        "min_train_samples": 300,
        "walk_forward_splits": 4,
        "bootstrap_snapshot_exchange": "binance_usdm",
        "historical_open_interest_source": "tardis",
        "tardis_api_key": os.environ.get("TARDIS_API_KEY"),
        "coinalyze_api_key": os.environ.get("COINALYZE_API_KEY"),
        "coinalyze_enabled": True,
        "coinalyze_symbols_by_coin": {"BTC": "BTC", "ETH": "ETH", "SOL": "SOL"},
        "daily_macro_features_enabled": daily_macro_features_enabled,
        "history_backfill_days": int(history_backfill_days),
        "high_confidence_target_coverage": 0.30,
        "feature_windows": [3, 6, 12, 24, 48],
    }
    if target_move_threshold_pct_overrides_by_coin_horizon is None:
        quant_kwargs["target_move_threshold_pct_overrides_by_coin_horizon"] = {"ETH:4h": 0.0025}
    else:
        quant_kwargs["target_move_threshold_pct_overrides_by_coin_horizon"] = target_move_threshold_pct_overrides_by_coin_horizon
    if probability_calibration_mode_by_coin_horizon is not None:
        quant_kwargs["probability_calibration_mode_by_coin_horizon"] = probability_calibration_mode_by_coin_horizon
    settings = SystemSettings(
        runtime_root=runtime_root,
        bus=BusSettings(rabbitmq_url="amqp://guest:guest@127.0.0.1:5672/%2F", exchange_name="benchmark.topic"),
        storage=StorageSettings(sqlite_path=runtime_root / "state" / "benchmark.db"),
        quant=QuantSettings(**quant_kwargs),
        execution=ExecutionSettings(
            exchange="coinbase_intx",
            supported_coins=list(COINS),
            live_enabled=False,
            max_leverage=5.0,
            max_total_exposure_pct_of_exposure_budget=100.0,
            max_order_share_pct_of_exposure_budget=66.0,
            max_position_share_pct_of_exposure_budget=100.0,
        ),
        workflow=WorkflowSettings(
            owner_channel="benchmark",
            owner_to="benchmark",
            owner_account_id="benchmark",
        ),
        agents=AgentSettings(),
        notification=NotificationSettings(default_channel="benchmark", default_recipient="benchmark"),
    )
    settings.quant.forecast_horizons = effective_horizons
    settings.quant.forecast_horizon_bars = primary_horizon_bars
    return settings


def _extract_current_meta(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "training_scope": meta.get("training_scope"),
        "panel_coins": meta.get("panel_coins", []),
        "panel_training_rows": meta.get("panel_training_rows"),
        "coin_training_rows": meta.get("coin_training_rows"),
        "validation_accuracy": meta.get("validation_accuracy"),
        "validation_macro_f1": meta.get("validation_macro_f1"),
        "validation_brier": meta.get("validation_brier"),
        "validation_log_loss": meta.get("validation_log_loss"),
        "validation_ece": meta.get("validation_ece"),
        "validation_classwise_ece": meta.get("validation_classwise_ece", {}),
        "high_confidence_metrics": meta.get("high_confidence_metrics", {}),
        "regime_metrics": meta.get("regime_metrics", {}),
        "snapshot_quality": meta.get("snapshot_quality", {}),
        "daily_feature_coverage": meta.get("daily_feature_coverage", {}),
        "coinalyze_enabled": meta.get("coinalyze_enabled", False),
        "coinalyze_history_summary": meta.get("coinalyze_history_summary", {}),
        "tardis_monthly_anchor_summary": meta.get("tardis_monthly_anchor_summary", {}),
        "threshold_diagnostics": meta.get("threshold_diagnostics", {}),
        "label_threshold_pct": meta.get("label_threshold_pct"),
        "probability_calibration_mode": meta.get("probability_calibration_mode", "dirichlet"),
        "label_diagnostics": meta.get("label_diagnostics", {}),
        "classwise_ece_before_post_calibration": meta.get("classwise_ece_before_post_calibration", {}),
        "classwise_ece_after_post_calibration": meta.get("classwise_ece_after_post_calibration", {}),
        "flat_class_post_calibration_metrics": meta.get("flat_class_post_calibration_metrics", {}),
        "specialist_summary": meta.get("specialist_summary", {}),
        "acceptance_score_mode": meta.get("acceptance_score_mode"),
        "acceptance_score_weights": meta.get("acceptance_score_weights", {}),
        "acceptance_score_metrics": meta.get("acceptance_score_metrics", {}),
        "regime_acceptance_policy": meta.get("regime_acceptance_policy", {}),
        "walk_forward": meta.get("walk_forward", {}),
        "interaction_features": meta.get("interaction_features", []),
        "12h_feature_family_summary": meta.get("12h_feature_family_summary", {}),
        "history_bars": meta.get("history_bars"),
    }


def run_current_benchmark(
    output_dir: Path,
    *,
    profile: str,
    settings: SystemSettings,
    shared_cache_root: Path | None = None,
    horizons: tuple[str, ...] = HORIZONS,
) -> dict[str, Any]:
    runtime_root = output_dir / f"current-runtime-{profile}"
    artifact_root = runtime_root / "models" / "perps"
    runtime_root.mkdir(parents=True, exist_ok=True)
    client = PublicCoinbaseCandleClient()
    trainer = DirectQuantTrainer(
        client=client,
        runtime=settings,
        artifact_root=artifact_root,
    )
    if shared_cache_root is not None:
        manifest = json.loads(history_manifest_path(shared_cache_root).read_text())
        trainer.candle_cache_dir = Path(manifest["candles_cache_dir"])
        trainer.snapshot_cache_dir = Path(manifest["snapshots_cache_dir"])
        trainer.candle_now = datetime.fromisoformat(manifest["window_end_utc"]).astimezone(UTC)
        trainer.snapshot_feature_provider = build_snapshot_provider_from_settings(
            settings=settings,
            cache_dir=trainer.snapshot_cache_dir,
        )
    try:
        trainer.retrain(list(COINS))
    finally:
        if hasattr(trainer.snapshot_feature_provider, "close"):
            trainer.snapshot_feature_provider.close()
        if hasattr(trainer.daily_macro_feature_provider, "close"):
            trainer.daily_macro_feature_provider.close()
        client.close()

    summary: dict[str, Any] = {"system": "current", "profile": profile, "artifact_root": str(artifact_root), "coins": {}}
    for coin in COINS:
        summary["coins"][coin] = {}
        for horizon in horizons:
            meta_path = artifact_root / coin / horizon / "meta.json"
            summary["coins"][coin][horizon] = _extract_current_meta(json.loads(meta_path.read_text()))
    return summary


def load_current_benchmark_summary(*, artifact_root: Path, profile: str, horizons: tuple[str, ...] = HORIZONS) -> dict[str, Any]:
    summary: dict[str, Any] = {"system": "current", "profile": profile, "artifact_root": str(artifact_root), "coins": {}}
    for coin in COINS:
        summary["coins"][coin] = {}
        for horizon in horizons:
            meta_path = artifact_root / coin / horizon / "meta.json"
            summary["coins"][coin][horizon] = _extract_current_meta(json.loads(meta_path.read_text()))
    return summary


def _baseline_helper_script(horizons: tuple[str, ...] = HORIZONS) -> str:
    script = textwrap.dedent(
        """
        from __future__ import annotations

        import gzip
        import json
        import ssl
        import sys
        from collections import deque
        from datetime import UTC, datetime
        from decimal import Decimal
        from pathlib import Path

        import certifi
        import httpx
        import joblib
        import numpy as np
        from sklearn.metrics import log_loss

        from openclaw_trader.config import (
            AppConfig,
            DispatchConfig,
            ModelConfig,
            NewsConfig,
            PerpConfig,
            RiskConfig,
            RuntimeConfig,
            StrategyConfig,
            WorkflowConfig,
        )
        from openclaw_trader.market_intelligence.binance_backfill import backfill_binance_perp_market_snapshots
        from openclaw_trader.market_intelligence.features import build_supervised_dataset
        from openclaw_trader.models import Candle
        from openclaw_trader.models import PerpSnapshot
        from openclaw_trader.market_intelligence.pipeline import PerpModelService
        from openclaw_trader.state import StateStore


        COINS = tuple(item.strip().upper() for item in sys.argv[1].split(",") if item.strip())
        OUTPUT_PATH = Path(sys.argv[2])
        MANIFEST_PATH = Path(sys.argv[3])
        COVERAGES = (0.2, 0.3, 0.4)
        HORIZONS = __HORIZONS_PLACEHOLDER__
        MANIFEST = json.loads(MANIFEST_PATH.read_text())
        CANDLE_ROOT = Path(MANIFEST["candles_cache_dir"])
        SNAPSHOT_ROOT = Path(MANIFEST["snapshots_cache_dir"])
        WINDOW_END = datetime.fromisoformat(MANIFEST["window_end_utc"]).astimezone(UTC)


        def normalize_candle_timestamp(raw_start: int) -> datetime | None:
            value = int(raw_start)
            magnitude = abs(value)
            if magnitude >= 1_000_000_000_000:
                return datetime.fromtimestamp(value / 1000.0, tz=UTC)
            if magnitude >= 1_000_000_000:
                return datetime.fromtimestamp(value, tz=UTC)
            return None


        def load_cached_candles(coin: str, interval: str) -> list[Candle]:
            path = CANDLE_ROOT / f"{coin.upper()}_{interval}.joblib"
            payload = joblib.load(path)
            candles = []
            for raw_payload in payload.values():
                candles.append(raw_payload if isinstance(raw_payload, Candle) else Candle(**raw_payload))
            frozen_end_ts = int(WINDOW_END.timestamp())
            return sorted(
                [item for item in candles if int(item.start) <= frozen_end_ts],
                key=lambda candle: candle.start,
            )


        def load_snapshot_payload(coin: str, interval: str) -> dict[str, dict[int, float]]:
            path = SNAPSHOT_ROOT / "normalized" / f"{coin.upper()}_{interval}_hybrid_snapshot.joblib"
            payload = joblib.load(path)
            return {
                "funding_rates": {int(key): float(value) for key, value in dict(payload.get("funding_rates", {})).items()},
                "premiums": {int(key): float(value) for key, value in dict(payload.get("premiums", {})).items()},
                "quote_volumes": {int(key): float(value) for key, value in dict(payload.get("quote_volumes", {})).items()},
                "open_interest": {int(key): float(value) for key, value in dict(payload.get("open_interest", {})).items()},
            }


        def rolling_day_notional_volumes(quote_volume_by_ts: dict[int, float], *, window_bars: int = 96) -> dict[int, float]:
            running = Decimal("0")
            queue = deque()
            result = {}
            for ts in sorted(quote_volume_by_ts.keys()):
                value = Decimal(str(quote_volume_by_ts[ts]))
                queue.append(value)
                running += value
                if len(queue) > window_bars:
                    running -= queue.popleft()
                result[ts] = float(running)
            return result


        def latest_at_or_before(series: dict[int, float], timestamp_ms: int) -> float | None:
            latest_value = None
            for ts in sorted(series.keys()):
                if ts > timestamp_ms:
                    break
                latest_value = float(series[ts])
            return latest_value


        def seed_snapshots(state: StateStore, *, coin: str, interval: str) -> None:
            candles = load_cached_candles(coin, interval)
            payload = load_snapshot_payload(coin, interval)
            day_volumes = rolling_day_notional_volumes(payload["quote_volumes"])
            for candle in candles:
                candle_time = normalize_candle_timestamp(candle.start)
                if candle_time is None:
                    continue
                ts_ms = int(candle_time.timestamp() * 1000)
                price = Decimal(str(candle.close))
                state.record_perp_market_snapshot(
                    PerpSnapshot(
                        exchange="binance_usdm",
                        coin=coin.upper(),
                        mark_price=price,
                        oracle_price=price,
                        mid_price=price,
                        funding_rate=(
                            Decimal(str(value))
                            if (value := latest_at_or_before(payload["funding_rates"], ts_ms)) is not None
                            else None
                        ),
                        premium=(
                            Decimal(str(value))
                            if (value := latest_at_or_before(payload["premiums"], ts_ms)) is not None
                            else None
                        ),
                        open_interest=(
                            Decimal(str(value))
                            if (value := latest_at_or_before(payload["open_interest"], ts_ms)) is not None
                            else None
                        ),
                        day_notional_volume=(
                            Decimal(str(value))
                            if (value := latest_at_or_before(day_volumes, ts_ms)) is not None
                            else None
                        ),
                        fetched_at=candle_time,
                    ),
                    now=candle_time,
                )


        class CachedCoinbaseEngine:
            def candles(self, coin: str | None = None, interval: str = "15m", lookback: int = 48):
                candles = load_cached_candles((coin or "BTC").upper(), interval)
                return candles[-lookback:]

        def normalize_probabilities(probabilities: np.ndarray) -> np.ndarray:
            probs = np.asarray(probabilities, dtype=np.float64)
            probs = np.clip(probs, 1e-9, 1.0)
            row_sums = probs.sum(axis=1, keepdims=True)
            row_sums[row_sums == 0] = 1.0
            return probs / row_sums


        def multiclass_brier_score(y_true: np.ndarray, probabilities: np.ndarray) -> float:
            probs = normalize_probabilities(probabilities)
            if len(y_true) == 0:
                return 0.0
            target = np.zeros_like(probs)
            target[np.arange(len(y_true)), y_true.astype(int)] = 1.0
            return float(np.mean(np.sum((probs - target) ** 2, axis=1)))


        def expected_calibration_error(y_true: np.ndarray, probabilities: np.ndarray, *, bins: int = 10) -> float:
            probs = normalize_probabilities(probabilities)
            if len(y_true) == 0:
                return 0.0
            predicted = np.argmax(probs, axis=1)
            confidence = np.max(probs, axis=1)
            correctness = (predicted == y_true).astype(np.float64)
            edges = np.linspace(0.0, 1.0, bins + 1)
            ece = 0.0
            for start, end in zip(edges[:-1], edges[1:]):
                if end >= 1.0:
                    mask = (confidence >= start) & (confidence <= end)
                else:
                    mask = (confidence >= start) & (confidence < end)
                if not np.any(mask):
                    continue
                ece += float(np.mean(mask)) * abs(float(np.mean(correctness[mask])) - float(np.mean(confidence[mask])))
            return float(ece)


        def classwise_expected_calibration_error(y_true: np.ndarray, probabilities: np.ndarray, *, bins: int = 10) -> dict[str, float]:
            probs = normalize_probabilities(probabilities)
            results = {}
            labels = ("short", "flat", "long")
            for class_idx, label in enumerate(labels):
                class_probs = probs[:, class_idx]
                class_target = (y_true == class_idx).astype(np.float64)
                edges = np.linspace(0.0, 1.0, bins + 1)
                ece = 0.0
                for start, end in zip(edges[:-1], edges[1:]):
                    if end >= 1.0:
                        mask = (class_probs >= start) & (class_probs <= end)
                    else:
                        mask = (class_probs >= start) & (class_probs < end)
                    if not np.any(mask):
                        continue
                    ece += float(np.mean(mask)) * abs(float(np.mean(class_target[mask])) - float(np.mean(class_probs[mask])))
                results[label] = round(float(ece), 6)
            return results


        def build_fixed_coverage_mask(probabilities: np.ndarray, coverage: float) -> np.ndarray:
            probs = normalize_probabilities(probabilities)
            if len(probs) == 0:
                return np.zeros((0,), dtype=bool)
            keep_count = min(len(probs), max(1, int(np.ceil(len(probs) * coverage))))
            order = np.argsort(-np.max(probs, axis=1), kind="mergesort")
            accepted = np.zeros(len(probs), dtype=bool)
            accepted[order[:keep_count]] = True
            return accepted


        def precision_at_fixed_coverages(
            y_true: np.ndarray,
            probabilities: np.ndarray,
            net_long_returns: np.ndarray,
            net_short_returns: np.ndarray,
        ) -> dict[str, dict[str, float]]:
            probs = normalize_probabilities(probabilities)
            if len(y_true) == 0:
                return {}
            prediction = np.argmax(probs, axis=1)
            realized_returns = np.zeros(len(prediction), dtype=np.float64)
            realized_returns[prediction == 0] = net_short_returns[prediction == 0]
            realized_returns[prediction == 2] = net_long_returns[prediction == 2]
            results = {}
            for coverage in COVERAGES:
                accepted = build_fixed_coverage_mask(probs, coverage)
                trade_mask = accepted & (prediction != 1)
                results[f"{int(round(coverage * 100))}%"] = {
                    "target_coverage": round(float(coverage), 4),
                    "achieved_coverage": round(float(np.mean(accepted)), 4),
                    "precision": round(float(np.mean(prediction[accepted] == y_true[accepted])) if np.any(accepted) else 0.0, 4),
                    "trade_precision": round(float(np.mean(realized_returns[trade_mask] > 0)) if np.any(trade_mask) else 0.0, 4),
                    "trade_coverage": round(float(np.mean(trade_mask)), 4),
                    "avg_net_return": round(float(np.mean(realized_returns[trade_mask])) if np.any(trade_mask) else 0.0, 6),
                }
            return results


        def summarize_regime_metrics(
            y_true: np.ndarray,
            probabilities: np.ndarray,
            regime_labels: np.ndarray,
            net_long_returns: np.ndarray,
            net_short_returns: np.ndarray,
        ) -> dict[str, object]:
            probs = normalize_probabilities(probabilities)
            accepted = build_fixed_coverage_mask(probs, 0.30)
            prediction = np.argmax(probs, axis=1)
            realized_returns = np.zeros(len(prediction), dtype=np.float64)
            realized_returns[prediction == 0] = net_short_returns[prediction == 0]
            realized_returns[prediction == 2] = net_long_returns[prediction == 2]
            by_regime = {}
            precisions = []
            for label in sorted({str(item) for item in regime_labels}):
                mask = (regime_labels == label) & accepted
                if not np.any(mask):
                    continue
                trade_mask = mask & (prediction != 1)
                precision = float(np.mean(prediction[mask] == y_true[mask]))
                precisions.append(precision)
                by_regime[label] = {
                    "rows": int(np.sum(mask)),
                    "coverage": round(float(np.mean(mask)), 4),
                    "precision": round(precision, 4),
                    "trade_precision": round(float(np.mean(realized_returns[trade_mask] > 0)) if np.any(trade_mask) else 0.0, 4),
                    "avg_net_return": round(float(np.mean(realized_returns[trade_mask])) if np.any(trade_mask) else 0.0, 6),
                }
            if not precisions:
                return {"by_regime": {}, "precision_std": 0.0, "precision_range": 0.0}
            return {
                "by_regime": by_regime,
                "precision_std": round(float(np.std(precisions)), 6),
                "precision_range": round(float(max(precisions) - min(precisions)), 6),
            }


        def evaluate_horizon(service: PerpModelService, runtime: RuntimeConfig, engine: PublicCoinbaseEngine, coin: str, horizon: str):
            horizon_bars = int(runtime.model.forecast_horizons[horizon])
            candles = engine.candles(coin, interval=runtime.model.interval, lookback=runtime.model.history_bars)
            regime_payload = service._fit_regime_model(coin, candles)
            service._latest_regime_state_map = dict(regime_payload["state_map"])
            extra_columns = service._build_extra_feature_columns(coin, candles, regime_payload=regime_payload)
            dataset = build_supervised_dataset(
                candles,
                windows=runtime.model.feature_windows,
                horizon_bars=horizon_bars,
                move_threshold_pct=runtime.model.target_move_threshold_pct,
                round_trip_cost_pct=runtime.model.round_trip_cost_pct,
                extra_columns=extra_columns,
            )
            walk_forward = service._walk_forward_predictions(dataset)
            probabilities = walk_forward["blended_probs"]
            y_true = walk_forward["y"]
            base_metrics = service._prediction_metrics(
                y_true,
                probabilities,
                walk_forward["net_long_returns"],
                walk_forward["net_short_returns"],
            )
            return {
                "training_scope": "single_coin",
                "validation_accuracy": base_metrics["accuracy"],
                "validation_macro_f1": base_metrics["macro_f1"],
                "validation_brier": round(multiclass_brier_score(y_true, probabilities), 6),
                "validation_log_loss": round(float(log_loss(y_true, normalize_probabilities(probabilities), labels=[0, 1, 2])), 6),
                "validation_ece": round(expected_calibration_error(y_true, probabilities), 6),
                "validation_classwise_ece": classwise_expected_calibration_error(y_true, probabilities),
                "high_confidence_metrics": {
                    "metric": "top_probability_rank",
                    "precision_at_coverage": precision_at_fixed_coverages(
                        y_true,
                        probabilities,
                        walk_forward["net_long_returns"],
                        walk_forward["net_short_returns"],
                    ),
                },
                "regime_metrics": summarize_regime_metrics(
                    y_true,
                    probabilities,
                    walk_forward["regime_labels"],
                    walk_forward["net_long_returns"],
                    walk_forward["net_short_returns"],
                ),
                "walk_forward": walk_forward["summary"],
            }


        def main() -> None:
            runtime = RuntimeConfig(
                app=AppConfig(),
                risk=RiskConfig(),
                news=NewsConfig(),
                perps=PerpConfig(coins=list(COINS), coin=COINS[0], live_enabled=False),
                dispatch=DispatchConfig(),
                strategy=StrategyConfig(),
                model=ModelConfig(bootstrap_snapshot_exchange="binance_usdm"),
                workflow=WorkflowConfig(),
            )
            state = StateStore()
            for coin in COINS:
                seed_snapshots(state, coin=coin, interval=runtime.model.interval)
            engine = CachedCoinbaseEngine()
            service = PerpModelService(runtime, engine, state)
            output = {"system": "codex/dev", "coins": {}}
            for coin in COINS:
                output["coins"][coin] = {}
                for horizon in HORIZONS:
                    output["coins"][coin][horizon] = evaluate_horizon(service, runtime, engine, coin, horizon)
            OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2))


        if __name__ == "__main__":
            main()
        """
    ).strip()
    return script.replace("__HORIZONS_PLACEHOLDER__", repr(tuple(horizons)))


def run_codex_dev_benchmark(output_dir: Path, *, manifest_file: Path, horizons: tuple[str, ...] = HORIZONS) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    worktree_dir = output_dir / "_codex_dev_worktree"
    baseline_home = output_dir / "_codex_dev_home"
    baseline_json = output_dir / "codex_dev_benchmark.json"
    helper_script = output_dir / "_codex_dev_eval.py"

    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree_dir)],
        cwd=repo_root,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    shutil.rmtree(worktree_dir, ignore_errors=True)
    shutil.rmtree(baseline_home, ignore_errors=True)
    baseline_home.mkdir(parents=True, exist_ok=True)
    helper_script.write_text(_baseline_helper_script(horizons))
    try:
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(worktree_dir), "codex/dev"],
            cwd=repo_root,
            check=True,
        )
        env = dict(**os.environ)
        env["HOME"] = str(baseline_home)
        env["PYTHONPATH"] = str(worktree_dir / "src")
        subprocess.run(
            [sys.executable, str(helper_script), ",".join(COINS), str(baseline_json), str(manifest_file)],
            cwd=worktree_dir,
            env=env,
            check=True,
        )
        return json.loads(baseline_json.read_text())
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree_dir)],
            cwd=repo_root,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        shutil.rmtree(worktree_dir, ignore_errors=True)
        helper_script.unlink(missing_ok=True)


def _precision(summary: dict[str, Any], coin: str, horizon: str, bucket: str = "30%") -> float:
    return float(
        summary["coins"][coin][horizon]
        .get("high_confidence_metrics", {})
        .get("precision_at_coverage", {})
        .get(bucket, {})
        .get("precision", 0.0)
    )


def _coverage(summary: dict[str, Any], coin: str, horizon: str, bucket: str = "30%") -> float:
    return float(
        summary["coins"][coin][horizon]
        .get("high_confidence_metrics", {})
        .get("precision_at_coverage", {})
        .get(bucket, {})
        .get("achieved_coverage", 0.0)
    )


def _scalar(summary: dict[str, Any], coin: str, horizon: str, field: str) -> float:
    return float(summary["coins"][coin][horizon].get(field, 0.0))


def build_delta_report(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    by_coin: dict[str, Any] = {}
    current_ece_values: list[float] = []
    baseline_ece_values: list[float] = []
    current_12h_precisions: list[float] = []
    baseline_12h_precisions: list[float] = []
    current_4h_precisions: list[float] = []
    baseline_4h_precisions: list[float] = []
    btc_deltas: list[float] = []
    alt_deltas: list[float] = []
    min_current_coverage = 1.0

    for coin in COINS:
        by_coin[coin] = {}
        for horizon in HORIZONS:
            current_precision = _precision(current, coin, horizon)
            baseline_precision = _precision(baseline, coin, horizon)
            current_ece = _scalar(current, coin, horizon, "validation_ece")
            baseline_ece = _scalar(baseline, coin, horizon, "validation_ece")
            current_brier = _scalar(current, coin, horizon, "validation_brier")
            baseline_brier = _scalar(baseline, coin, horizon, "validation_brier")
            current_log_loss = _scalar(current, coin, horizon, "validation_log_loss")
            baseline_log_loss = _scalar(baseline, coin, horizon, "validation_log_loss")
            current_cov = _coverage(current, coin, horizon)
            baseline_cov = _coverage(baseline, coin, horizon)
            min_current_coverage = min(min_current_coverage, current_cov)
            by_coin[coin][horizon] = {
                "current_precision_30": round(current_precision, 4),
                "baseline_precision_30": round(baseline_precision, 4),
                "delta_precision_30": round(current_precision - baseline_precision, 4),
                "current_coverage_30": round(current_cov, 4),
                "baseline_coverage_30": round(baseline_cov, 4),
                "current_ece": round(current_ece, 6),
                "baseline_ece": round(baseline_ece, 6),
                "delta_ece": round(current_ece - baseline_ece, 6),
                "current_brier": round(current_brier, 6),
                "baseline_brier": round(baseline_brier, 6),
                "delta_brier": round(current_brier - baseline_brier, 6),
                "current_log_loss": round(current_log_loss, 6),
                "baseline_log_loss": round(baseline_log_loss, 6),
                "delta_log_loss": round(current_log_loss - baseline_log_loss, 6),
            }
            current_ece_values.append(current_ece)
            baseline_ece_values.append(baseline_ece)
            if horizon == "12h":
                current_12h_precisions.append(current_precision)
                baseline_12h_precisions.append(baseline_precision)
            if horizon == "4h":
                current_4h_precisions.append(current_precision)
                baseline_4h_precisions.append(baseline_precision)
            if coin == "BTC":
                btc_deltas.append(current_precision - baseline_precision)
            else:
                alt_deltas.append(current_precision - baseline_precision)

    current_avg_ece = sum(current_ece_values) / max(len(current_ece_values), 1)
    baseline_avg_ece = sum(baseline_ece_values) / max(len(baseline_ece_values), 1)
    avg_12h_delta = (sum(current_12h_precisions) / max(len(current_12h_precisions), 1)) - (
        sum(baseline_12h_precisions) / max(len(baseline_12h_precisions), 1)
    )
    avg_4h_delta = (sum(current_4h_precisions) / max(len(current_4h_precisions), 1)) - (
        sum(baseline_4h_precisions) / max(len(baseline_4h_precisions), 1)
    )
    ece_improvement_ratio = 0.0 if baseline_avg_ece <= 0 else 1.0 - (current_avg_ece / baseline_avg_ece)
    headline_checks = {
        "avg_12h_precision_30_delta_gte_3pp": avg_12h_delta >= 0.03,
        "avg_4h_precision_30_delta_gte_2pp": avg_4h_delta >= 0.02,
        "avg_ece_improved_gte_25pct": ece_improvement_ratio >= 0.25,
        "coverage_30_not_below_20pct": min_current_coverage >= 0.20,
        "eth_or_sol_improved_gte_1pp": max(alt_deltas) >= 0.01 if alt_deltas else False,
        "btc_not_worse_than_minus_1pp": min(btc_deltas) >= -0.01 if btc_deltas else False,
    }
    return {
        "by_coin": by_coin,
        "headline": {
            "avg_12h_precision_30_delta": round(avg_12h_delta, 4),
            "avg_4h_precision_30_delta": round(avg_4h_delta, 4),
            "avg_current_ece": round(current_avg_ece, 6),
            "avg_baseline_ece": round(baseline_avg_ece, 6),
            "ece_improvement_ratio": round(ece_improvement_ratio, 4),
            "min_current_coverage_30": round(min_current_coverage, 4),
            "checks": headline_checks,
            "all_passed": all(headline_checks.values()),
        },
    }


def build_eth4h_headline(summary: dict[str, Any]) -> dict[str, Any]:
    payload = summary["coins"]["ETH"]["4h"]
    return {
        "eth4h_label_threshold": payload.get("label_threshold_pct"),
        "probability_calibration_mode": payload.get("probability_calibration_mode", "dirichlet"),
        "precision_at_coverage": payload.get("high_confidence_metrics", {}).get("precision_at_coverage", {}),
        "validation_ece": payload.get("validation_ece"),
        "validation_classwise_ece": payload.get("validation_classwise_ece", {}),
        "classwise_ece_before_post_calibration": payload.get("classwise_ece_before_post_calibration", {}),
        "classwise_ece_after_post_calibration": payload.get("classwise_ece_after_post_calibration", {}),
        "flat_class_post_calibration_metrics": payload.get("flat_class_post_calibration_metrics", {}),
        "trade_precision_30": payload.get("high_confidence_metrics", {})
        .get("precision_at_coverage", {})
        .get("30%", {})
        .get("trade_precision"),
        "regime_metrics": payload.get("regime_metrics", {}),
        "accepted_slice_distribution": payload.get("label_diagnostics", {})
        .get("high_confidence_slice", {})
        .get("distribution", {}),
        "acceptance_score_mode": payload.get("acceptance_score_mode"),
        "acceptance_score_weights": payload.get("acceptance_score_weights", {}),
        "regime_acceptance_policy": payload.get("regime_acceptance_policy", {}),
        "history_bars": payload.get("history_bars"),
    }


def history_candidate_sort_key(
    summary: dict[str, Any],
    vs_baseline: dict[str, Any],
    vs_dev: dict[str, Any],
) -> tuple[float, float, float, float]:
    eth_gain = float(vs_baseline["by_coin"]["ETH"]["4h"]["delta_precision_30"])
    avg_4h_dev = float(vs_dev["headline"]["avg_4h_precision_30_delta"])
    avg_12h_dev = float(vs_dev["headline"]["avg_12h_precision_30_delta"])
    ece_gain = float(vs_dev["headline"]["ece_improvement_ratio"])
    return (eth_gain, avg_4h_dev, avg_12h_dev, ece_gain)


def history_candidate_is_viable(vs_baseline: dict[str, Any], vs_dev: dict[str, Any]) -> bool:
    eth_gain = float(vs_baseline["by_coin"]["ETH"]["4h"]["delta_precision_30"])
    avg_4h_vs_dev = float(vs_dev["headline"]["avg_4h_precision_30_delta"])
    avg_12h_vs_dev = float(vs_dev["headline"]["avg_12h_precision_30_delta"])
    return eth_gain > 0.0 and avg_4h_vs_dev >= 0.05 and avg_12h_vs_dev >= 0.10


def eth4h_profile_is_viable(vs_baseline: dict[str, Any] | None, vs_dev: dict[str, Any] | None) -> bool:
    if not vs_baseline or not vs_dev:
        return False
    eth_vs_baseline = float(vs_baseline["by_coin"]["ETH"]["4h"]["delta_precision_30"])
    eth_vs_dev = float(vs_dev["by_coin"]["ETH"]["4h"]["delta_precision_30"])
    eth_ece_delta = float(vs_baseline["by_coin"]["ETH"]["4h"]["delta_ece"])
    btc_vs_baseline = float(vs_baseline["by_coin"]["BTC"]["4h"]["delta_precision_30"])
    sol_vs_baseline = float(vs_baseline["by_coin"]["SOL"]["4h"]["delta_precision_30"])
    avg_12h_vs_dev = float(vs_dev["headline"]["avg_12h_precision_30_delta"])
    return (
        eth_vs_baseline >= 0.03
        and eth_vs_dev >= 0.02
        and eth_ece_delta <= 0.005
        and btc_vs_baseline >= -0.01
        and sol_vs_baseline >= -0.01
        and avg_12h_vs_dev >= 0.10
    )


def eth4h_profile_sort_key(vs_baseline: dict[str, Any] | None, vs_dev: dict[str, Any] | None) -> tuple[float, float, float]:
    if not vs_baseline or not vs_dev:
        return (-1.0, -1.0, -1.0)
    return (
        float(vs_baseline["by_coin"]["ETH"]["4h"]["delta_precision_30"]),
        float(vs_dev["by_coin"]["ETH"]["4h"]["delta_precision_30"]),
        -float(vs_baseline["by_coin"]["ETH"]["4h"]["delta_ece"]),
    )


def render_markdown_report(
    current_profiles: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    deltas_vs_dev: dict[str, dict[str, Any]],
    deltas_vs_baseline: dict[str, dict[str, Any]],
    output_dir: Path,
    history_manifest: dict[str, Any],
) -> str:
    viable_profiles = [
        name
        for name in ("eth4h_specialist", "eth4h_ranking_regime", "eth4h_ranking", "eth4h_history_sweep")
        if name in current_profiles and eth4h_profile_is_viable(deltas_vs_baseline.get(name), deltas_vs_dev.get(name))
    ]
    selected_profile = (
        max(viable_profiles, key=lambda name: eth4h_profile_sort_key(deltas_vs_baseline.get(name), deltas_vs_dev.get(name)))
        if viable_profiles
        else "baseline_long_history"
    )
    selected_current = current_profiles[selected_profile]
    selected_delta = deltas_vs_dev[selected_profile]
    selected_vs_baseline = deltas_vs_baseline.get(selected_profile, {"by_coin": {"ETH": {"4h": {"delta_precision_30": 0.0}}}})

    def render_precision_table(summary: dict[str, Any], coin: str, horizon: str) -> list[str]:
        table = (
            summary["coins"][coin][horizon]
            .get("high_confidence_metrics", {})
            .get("precision_at_coverage", {})
        )
        if not table:
            return ["- no high-confidence table available"]
        lines: list[str] = []
        for bucket in COVERAGE_BUCKETS:
            payload = table.get(bucket, {})
            lines.append(
                f"- `{bucket}`: precision=`{payload.get('precision')}`, coverage=`{payload.get('achieved_coverage')}`, trade_precision=`{payload.get('trade_precision')}`, avg_net_return=`{payload.get('avg_net_return')}`"
            )
        return lines

    def render_classwise_ece(summary: dict[str, Any], coin: str, horizon: str) -> list[str]:
        payload = summary["coins"][coin][horizon].get("validation_classwise_ece", {})
        if not payload:
            return ["- no classwise ECE available"]
        return [f"- `{label}`: `{value}`" for label, value in payload.items()]

    def render_regime_metrics(summary: dict[str, Any], coin: str, horizon: str) -> list[str]:
        regime_metrics = summary["coins"][coin][horizon].get("regime_metrics", {})
        by_regime = regime_metrics.get("by_regime", {})
        lines = [
            f"- `precision_std`: `{regime_metrics.get('precision_std', 0.0)}`",
            f"- `precision_range`: `{regime_metrics.get('precision_range', 0.0)}`",
        ]
        for regime_label, payload in by_regime.items():
            lines.append(
                f"- `{regime_label}`: rows=`{payload.get('rows')}`, coverage=`{payload.get('coverage')}`, precision=`{payload.get('precision')}`, trade_precision=`{payload.get('trade_precision')}`, avg_net_return=`{payload.get('avg_net_return')}`"
            )
        return lines

    lines = [
        "# Quant Intelligence Benchmark",
        "",
        f"- Generated at: `{datetime.now(UTC).isoformat()}`",
        f"- Output dir: `{output_dir}`",
        f"- Selected profile: `{selected_profile}`",
        f"- Selected profile artifact root: `{selected_current.get('artifact_root')}`",
        "",
        "## Phase Headlines",
        "",
    ]
    free_data_stack_summary = {
        "price": "Coinbase 15m candles",
        "snapshot": "Binance funding/premium/quote_volume/recent_oi",
        "monthly_oi_anchor": "Tardis monthly first-day public CSV",
        "daily_free_supplement": "Coinalyze daily OI/funding/long-short ratio (optional)",
    }
    lines.extend(
        [
            "## Free Data Stack",
            "",
            f"- `summary`: `{free_data_stack_summary}`",
            f"- `history_window`: `{history_manifest.get('window_start_utc')} -> {history_manifest.get('window_end_utc')}`",
            "",
        ]
    )
    for profile in (*CURRENT_PROFILES, "eth4h_specialist"):
        if profile not in current_profiles:
            continue
        headline = deltas_vs_dev[profile]["headline"]
        baseline_delta = deltas_vs_baseline.get(profile, {"by_coin": {"ETH": {"4h": {"delta_precision_30": 0.0}}}})
        lines.extend(
            [
                f"### {profile}",
                "",
                f"- `avg_12h_precision_30_delta`: `{headline['avg_12h_precision_30_delta']}`",
                f"- `avg_4h_precision_30_delta`: `{headline['avg_4h_precision_30_delta']}`",
                f"- `ece_improvement_ratio`: `{headline['ece_improvement_ratio']}`",
                f"- `min_current_coverage_30`: `{headline['min_current_coverage_30']}`",
                f"- `eth4h_precision_30_delta_vs_baseline`: `{baseline_delta['by_coin']['ETH']['4h']['delta_precision_30']}`",
                f"- `all_passed`: `{headline['all_passed']}`",
                "",
            ]
        )
    eth4h_headline = build_eth4h_headline(selected_current)
    lines.extend(
        [
            "## ETH 4h Headline",
            "",
            f"- `precision_20`: `{eth4h_headline['precision_at_coverage'].get('20%', {}).get('precision')}`",
            f"- `precision_30`: `{eth4h_headline['precision_at_coverage'].get('30%', {}).get('precision')}`",
            f"- `precision_40`: `{eth4h_headline['precision_at_coverage'].get('40%', {}).get('precision')}`",
            f"- `validation_ece`: `{eth4h_headline['validation_ece']}`",
            f"- `trade_precision_30`: `{eth4h_headline['trade_precision_30']}`",
            f"- `accepted_slice_distribution`: `{eth4h_headline['accepted_slice_distribution']}`",
            f"- `acceptance_score_mode`: `{eth4h_headline['acceptance_score_mode']}`",
            f"- `acceptance_score_weights`: `{eth4h_headline['acceptance_score_weights']}`",
            f"- `regime_acceptance_policy`: `{eth4h_headline['regime_acceptance_policy']}`",
            f"- `history_bars`: `{eth4h_headline['history_bars']}`",
            "",
        ]
    )
    lines.extend(["## Selected Profile Precision@30 Deltas", ""])
    for coin in COINS:
        lines.append(f"### {coin}")
        lines.append("")
        for horizon in HORIZONS:
            row = selected_delta["by_coin"][coin][horizon]
            lines.append(
                f"- `{horizon}`: current=`{row['current_precision_30']}`, baseline=`{row['baseline_precision_30']}`, delta=`{row['delta_precision_30']}`, coverage=`{row['current_coverage_30']}`"
            )
        lines.append("")
    lines.extend(["## Selected Profile Detailed Metrics", ""])
    for coin in COINS:
        for horizon in HORIZONS:
            current_payload = selected_current["coins"][coin][horizon]
            baseline_payload = baseline["coins"][coin][horizon]
            lines.extend(
                [
                    f"### {coin} {horizon}",
                    "",
                    f"- `current_validation_accuracy`: `{current_payload.get('validation_accuracy')}`",
                    f"- `baseline_validation_accuracy`: `{baseline_payload.get('validation_accuracy')}`",
                    f"- `current_validation_macro_f1`: `{current_payload.get('validation_macro_f1')}`",
                    f"- `baseline_validation_macro_f1`: `{baseline_payload.get('validation_macro_f1')}`",
                    f"- `current_validation_brier`: `{current_payload.get('validation_brier')}`",
                    f"- `baseline_validation_brier`: `{baseline_payload.get('validation_brier')}`",
                    f"- `current_validation_log_loss`: `{current_payload.get('validation_log_loss')}`",
                    f"- `baseline_validation_log_loss`: `{baseline_payload.get('validation_log_loss')}`",
                    f"- `current_validation_ece`: `{current_payload.get('validation_ece')}`",
                    f"- `baseline_validation_ece`: `{baseline_payload.get('validation_ece')}`",
                    "",
                    "#### Current Precision At Coverage",
                    "",
                    *render_precision_table(selected_current, coin, horizon),
                    "",
                    "#### Baseline Precision At Coverage",
                    "",
                    *render_precision_table(baseline, coin, horizon),
                    "",
                    "#### Current Classwise ECE",
                    "",
                    *render_classwise_ece(selected_current, coin, horizon),
                    "",
                    "#### Baseline Classwise ECE",
                    "",
                    *render_classwise_ece(baseline, coin, horizon),
                    "",
                    "#### Current Regime Split",
                    "",
                    *render_regime_metrics(selected_current, coin, horizon),
                    "",
                    "#### Baseline Regime Split",
                    "",
                    *render_regime_metrics(baseline, coin, horizon),
                    "",
                ]
            )
    lines.extend(["## Selected Profile Calibration Deltas", ""])
    for coin in COINS:
        for horizon in HORIZONS:
            row = selected_delta["by_coin"][coin][horizon]
            lines.append(
                f"- `{coin} {horizon}`: ECE delta=`{row['delta_ece']}`, Brier delta=`{row['delta_brier']}`, LogLoss delta=`{row['delta_log_loss']}`"
            )
    lines.extend(
        [
            "",
            "## Selected Profile Vs Baseline",
            "",
            f"- `ETH 4h delta_precision_30`: `{selected_vs_baseline['by_coin']['ETH']['4h']['delta_precision_30']}`",
            "",
            "## 12h Slow Feature Summary",
            "",
            f"- `ETH`: `{selected_current['coins']['ETH']['12h'].get('12h_feature_family_summary', {})}`",
            f"- `SOL`: `{selected_current['coins']['SOL']['12h'].get('12h_feature_family_summary', {})}`",
            f"- `coinalyze_coverage`: `{{'ETH': {selected_current['coins']['ETH']['12h'].get('coinalyze_history_summary', {})}, 'SOL': {selected_current['coins']['SOL']['12h'].get('coinalyze_history_summary', {})}}}`",
            f"- `monthly_oi_anchor_coverage`: `{{'ETH': {selected_current['coins']['ETH']['12h'].get('tardis_monthly_anchor_summary', {})}, 'SOL': {selected_current['coins']['SOL']['12h'].get('tardis_monthly_anchor_summary', {})}}}`",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark current QI against codex/dev baseline.")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--baseline-json", type=Path, default=None)
    args = parser.parse_args()

    output_dir = args.output_dir or Path(tempfile.mkdtemp(prefix="openclaw-qi-benchmark-"))
    output_dir.mkdir(parents=True, exist_ok=True)
    shared_cache_root = output_dir / "_shared_history_cache"
    shared_cache_root.mkdir(parents=True, exist_ok=True)
    benchmark_settings = build_benchmark_settings(output_dir / "baseline_long_history")
    prepare_history_bundle(shared_cache_root, settings=benchmark_settings)
    baseline_long_history = run_current_benchmark(
        output_dir,
        profile="baseline_long_history",
        settings=benchmark_settings,
        shared_cache_root=shared_cache_root,
    )
    current_profiles: dict[str, dict[str, Any]] = {"baseline_long_history": baseline_long_history}

    if args.baseline_json is not None:
        baseline_summary = json.loads(args.baseline_json.read_text())
    else:
        baseline_summary = run_codex_dev_benchmark(output_dir, manifest_file=history_manifest_path(shared_cache_root))

    deltas_vs_dev = {profile: build_delta_report(summary, baseline_summary) for profile, summary in current_profiles.items()}
    deltas_vs_baseline: dict[str, dict[str, Any]] = {}

    report_json = output_dir / "qi_benchmark_report.json"
    report_md = output_dir / "qi_benchmark_report.md"
    history_manifest = json.loads(history_manifest_path(shared_cache_root).read_text())
    payload = {
        "baseline_long_history": {
            "current": baseline_long_history,
            "vs_codex_dev": deltas_vs_dev["baseline_long_history"],
        },
        "profiles": {},
        "history_bundle_manifest": history_manifest,
        "free_data_stack_summary": {
            "price": "Coinbase 15m candles",
            "snapshot": "Binance funding/premium/quote_volume/recent_oi",
            "monthly_oi_anchor": "Tardis monthly first-day public CSV",
            "daily_free_supplement": "Coinalyze daily OI/funding/long-short ratio (optional)",
        },
        "baseline": baseline_summary,
    }
    report_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    report_md.write_text(render_markdown_report(current_profiles, baseline_summary, deltas_vs_dev, deltas_vs_baseline, output_dir, history_manifest))
    print(json.dumps({"output_dir": str(output_dir), "report_json": str(report_json), "report_md": str(report_md)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
