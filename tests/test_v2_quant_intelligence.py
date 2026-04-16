from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import joblib
import numpy as np

from openclaw_trader.modules.quant_intelligence.adapters import DirectArtifactQuantProvider, DirectQuantTrainer
from openclaw_trader.modules.quant_intelligence.support.snapshot_history import SnapshotFeaturePayload
from openclaw_trader.modules.quant_intelligence.service import QuantIntelligenceService
from openclaw_trader.shared.protocols import Candle

from .helpers_v2 import FakeMarketDataProvider, FakeQuantProvider, build_test_settings
from openclaw_trader.modules.trade_gateway.market_data.service import DataIngestService


class _DummyScaler:
    def transform(self, value):
        return value


class _DummyHmm:
    def predict(self, value):
        return np.asarray([0], dtype=np.int32)

    def predict_proba(self, value):
        return np.asarray([[0.9, 0.05, 0.05]], dtype=np.float64)


class _FakeCoinbaseClient:
    def __init__(self) -> None:
        now = datetime.now(UTC).replace(second=0, microsecond=0)
        self._candles = [
            Candle(
                start=int((now - timedelta(minutes=15 * (80 - idx))).timestamp()),
                low=Decimal("99") + Decimal(idx) * Decimal("0.1"),
                high=Decimal("101") + Decimal(idx) * Decimal("0.1"),
                open=Decimal("100") + Decimal(idx) * Decimal("0.1"),
                close=Decimal("100.2") + Decimal(idx) * Decimal("0.1"),
                volume=Decimal("1000") + Decimal(idx),
            )
            for idx in range(80)
        ]

    def get_public_candles(self, product_id: str, *, start: int, end: int, granularity: str, limit: int | None = None):
        candles = [candle for candle in self._candles if start <= candle.start <= end]
        if limit is not None:
            candles = candles[-limit:]
        return candles


class _FakeSnapshotFeatureProvider:
    def build_feature_payload(self, *, coin: str, candles: list[Candle], quant) -> SnapshotFeaturePayload:
        length = len(candles)
        columns = {
            "market_funding_rate": np.full(length, 0.001, dtype=np.float64),
            "market_funding_abs": np.full(length, 0.001, dtype=np.float64),
            "market_premium": np.full(length, 0.002, dtype=np.float64),
            "market_premium_abs": np.full(length, 0.002, dtype=np.float64),
            "market_open_interest_change_6": np.linspace(0.01, 0.05, length, dtype=np.float64),
            "market_open_interest_change_24": np.linspace(0.02, 0.06, length, dtype=np.float64),
            "market_day_volume_change_6": np.linspace(0.03, 0.07, length, dtype=np.float64),
            "market_day_volume_change_24": np.linspace(0.04, 0.08, length, dtype=np.float64),
            "market_snapshot_coverage": np.ones(length, dtype=np.float64),
            "market_snapshot_missing_any": np.zeros(length, dtype=np.float64),
            "market_open_interest_outlier_flag": np.zeros(length, dtype=np.float64),
            "market_day_volume_outlier_flag": np.zeros(length, dtype=np.float64),
            "market_funding_outlier_flag": np.zeros(length, dtype=np.float64),
        }
        return SnapshotFeaturePayload(
            columns=columns,
            sample_weights=np.ones(length, dtype=np.float64),
            quality_summary={"snapshot_avg_coverage": 1.0, "snapshot_rejected_rows": 0.0, "snapshot_downweighted_rows": 0.0},
        )


class QuantIntelligenceServiceTests(unittest.TestCase):
    def test_predict_market_returns_horizons(self) -> None:
        market = DataIngestService(FakeMarketDataProvider()).collect(trace_id="trace-1", coins=["BTC"])
        service = QuantIntelligenceService(FakeQuantProvider())
        forecasts = service.predict_market(market)
        self.assertEqual(forecasts["BTC"].horizons["12h"].side, "long")

    def test_direct_artifact_provider_predicts_from_saved_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            artifact_root = Path(tempdir) / "perps"
            for horizon in ("1h", "4h", "12h"):
                base = artifact_root / "BTC" / horizon
                base.mkdir(parents=True, exist_ok=True)
                (base / "meta.json").write_text(
                    json.dumps(
                        {
                            "coin": "BTC",
                            "horizon": horizon,
                            "trained_at": "2026-03-11T00:00:00+00:00",
                            "training_rows": 5800,
                            "validation_accuracy": 0.5,
                            "validation_macro_f1": 0.4,
                            "validation_brier": 0.12,
                            "validation_log_loss": 0.75,
                            "validation_ece": 0.08,
                            "blend_weight_lgbm": 0.6,
                            "feature_names": ["ret_1", "ret_6", "regime_state", "regime_confidence"],
                            "walk_forward": {"rows": 200},
                            "forecast_horizon_bars": {"1h": 4, "4h": 16, "12h": 48}[horizon],
                            "acceptance_policy": {
                                "mode": "threshold_filters",
                                "min_top_probability": 0.2,
                                "min_margin": 0.0,
                                "max_entropy": 1.0,
                                "target_coverage": 0.3,
                                "achieved_coverage": 0.3,
                                "achieved_precision": 0.8,
                            },
                            "calibrated_policy": {
                                "global": {
                                    "min_confidence": 0.2,
                                    "min_long_short_probability": 0.2,
                                    "meta_min_confidence": 0.1,
                                    "order_size_floor_ratio": 0.35,
                                    "order_size_ceiling_ratio": 1.0,
                                },
                                "global_metrics": {"trade_count": 42},
                                "regimes": {},
                            },
                            "regime_state_map": {"0": "bullish_trend"},
                        }
                    )
                )
                joblib.dump(
                    {
                        "scaler": _DummyScaler(),
                        "hmm": _DummyHmm(),
                        "feature_names": ["ret_1", "ret_6"],
                        "state_map": {"0": "bullish_trend"},
                    },
                    base / "regime.joblib",
                )
                joblib.dump(
                    {
                        "constant_probs": np.asarray([0.05, 0.1, 0.85], dtype=np.float64),
                        "meta_model": None,
                        "meta_calibrator": None,
                    },
                    base / "classifier.joblib",
                )

            market = DataIngestService(FakeMarketDataProvider()).collect(trace_id="trace-1", coins=["BTC"])
            provider = DirectArtifactQuantProvider(
                client=_FakeCoinbaseClient(),
                artifact_root=artifact_root,
                retrain_provider=FakeQuantProvider(),
            )
            forecasts = QuantIntelligenceService(provider).predict_market(market)
            self.assertEqual(forecasts["BTC"].horizons["12h"].side, "long")
            self.assertGreater(forecasts["BTC"].horizons["12h"].confidence, 0.6)
            self.assertEqual(forecasts["BTC"].horizons["12h"].abstain_state, "accepted")
            self.assertIn("long", forecasts["BTC"].horizons["12h"].calibrated_probabilities)

    def test_direct_quant_trainer_writes_artifacts_without_legacy_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            settings = build_test_settings(Path(tempdir) / "state" / "test.db")
            settings.quant.history_bars = 120
            settings.quant.min_train_samples = 20
            settings.quant.walk_forward_splits = 2
            settings.quant.feature_windows = [3, 6, 12]
            settings.quant.forecast_horizons = {"1h": 4, "4h": 8, "12h": 16}
            settings.quant.adaptive_labeling_enabled = True
            settings.quant.specialist_horizons = ["12h"]
            settings.quant.acceptance_score_components_by_horizon = {
                "4h": [
                    "calibrated_top_probability",
                    "top_two_margin",
                    "inverse_normalized_entropy",
                    "meta_trade_quality_probability",
                ]
            }
            settings.quant.regime_coverage_caps_by_coin_horizon = {"BTC:4h": {"bullish_trend": 0.2}}
            artifact_root = Path(tempdir) / "perps"
            trainer = DirectQuantTrainer(
                client=_FakeCoinbaseClient(),
                runtime=settings,
                artifact_root=artifact_root,
                snapshot_feature_provider=_FakeSnapshotFeatureProvider(),
            )

            result = trainer.retrain(["BTC"])

            self.assertIn("BTC", result)
            self.assertTrue((artifact_root / "BTC" / "1h" / "meta.json").exists())
            self.assertTrue((artifact_root / "BTC" / "4h" / "classifier.joblib").exists())
            self.assertTrue((artifact_root / "BTC" / "12h" / "calibration-report.md").exists())
            meta = json.loads((artifact_root / "BTC" / "4h" / "meta.json").read_text())
            self.assertIn("market_funding_rate", meta["market_snapshot_features"])
            self.assertIn("acceptance_policy", meta)
            self.assertIn("snapshot_quality", meta)
            self.assertEqual(meta["acceptance_score_mode"], "score_rank")
            self.assertIn("acceptance_score_weights", meta)
            self.assertIn("regime_acceptance_policy", meta)

    def test_direct_quant_trainer_supports_panel_training_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            settings = build_test_settings(Path(tempdir) / "state" / "test.db")
            settings.quant.history_bars = 120
            settings.quant.min_train_samples = 20
            settings.quant.walk_forward_splits = 2
            settings.quant.feature_windows = [3, 6, 12]
            settings.quant.forecast_horizons = {"1h": 4, "4h": 8, "12h": 16}
            settings.quant.adaptive_labeling_enabled = False
            settings.quant.training_history_bars_by_horizon = {"1h": 120, "4h": 180, "12h": 240}
            settings.quant.training_history_bars_overrides_by_coin_horizon = {"ETH:4h": 150}
            settings.quant.target_move_threshold_pct_overrides_by_coin_horizon = {"ETH:4h": 0.003}
            settings.quant.probability_calibration_mode_by_coin_horizon = {"ETH:4h": "flat_isotonic_rescale"}
            settings.quant.acceptance_score_weights_by_coin_horizon = {
                "ETH:4h": {"meta_trade_quality_probability": 1.0}
            }
            settings.quant.regime_coverage_caps_by_coin_horizon = {"ETH:4h": {"bullish_trend": 0.1}}
            settings.quant.specialist_coin_horizons = ["ETH:4h"]
            artifact_root = Path(tempdir) / "perps"
            trainer = DirectQuantTrainer(
                client=_FakeCoinbaseClient(),
                runtime=settings,
                artifact_root=artifact_root,
                snapshot_feature_provider=_FakeSnapshotFeatureProvider(),
            )

            result = trainer.retrain(["BTC", "ETH"])

            self.assertEqual(set(result.keys()), {"BTC", "ETH"})
            meta = json.loads((artifact_root / "ETH" / "4h" / "meta.json").read_text())
            self.assertEqual(meta["training_scope"], "panel")
            self.assertEqual(meta["panel_coins"], ["BTC", "ETH"])
            self.assertIn("high_confidence_metrics", meta)
            self.assertIn("regime_metrics", meta)
            self.assertIn("interaction_features", meta)
            self.assertIn("threshold_diagnostics", meta)
            self.assertIn("label_diagnostics", meta)
            self.assertEqual(meta["threshold_diagnostics"]["mode"], "fixed")
            self.assertTrue(meta["specialist_summary"]["enabled"])
            self.assertEqual(meta["history_bars"], 150)
            self.assertEqual(meta["label_threshold_pct"], 0.003)
            self.assertEqual(meta["probability_calibration_mode"], "flat_isotonic_rescale")
            self.assertEqual(meta["threshold_diagnostics"]["applied_threshold_pct"], 0.003)
            self.assertEqual(meta["threshold_diagnostics"]["threshold_source"], "coin_horizon_override")
            self.assertIn("classwise_ece_before_post_calibration", meta)
            self.assertIn("classwise_ece_after_post_calibration", meta)
            self.assertIn("active", meta["flat_class_post_calibration_metrics"])
            self.assertEqual(meta["acceptance_score_mode"], "score_rank")
            self.assertIn("acceptance_score_weights", meta)
            self.assertIn("acceptance_score_metrics", meta)
            self.assertTrue(meta["regime_acceptance_policy"]["active"])
            self.assertIn("jump_z_12", meta["interaction_features"])
            btc_meta = json.loads((artifact_root / "BTC" / "4h" / "meta.json").read_text())
            self.assertEqual(btc_meta["acceptance_score_mode"], "top_probability_rank")
            self.assertEqual(btc_meta["label_threshold_pct"], settings.quant.target_move_threshold_pct)
            self.assertEqual(btc_meta["probability_calibration_mode"], "dirichlet")
            self.assertEqual(btc_meta["threshold_diagnostics"]["threshold_source"], "global_default")
            classifier = joblib.load(artifact_root / "ETH" / "4h" / "classifier.joblib")
            self.assertIsNotNone(classifier["specialist_base_models"])
            self.assertIn("flat_class_calibrator", classifier)


if __name__ == "__main__":
    unittest.main()
