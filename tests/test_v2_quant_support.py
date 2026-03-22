from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

import joblib
import numpy as np

from openclaw_trader.config.models import QuantSettings
from openclaw_trader.modules.quant_intelligence.features import (
    build_adaptive_move_thresholds,
    build_asset_indicator_columns,
    build_interaction_feature_columns,
    build_long_horizon_feature_columns,
    build_supervised_dataset,
    combine_supervised_datasets,
    prepare_series,
)
from openclaw_trader.modules.trade_gateway.market_data.models import DataIngestBundle, MarketSnapshotNormalized
from openclaw_trader.modules.quant_intelligence.support import (
    apply_flat_isotonic_rescale,
    apply_dirichlet_calibration,
    backfill_candles_window,
    build_fixed_coverage_mask,
    build_high_confidence_policy,
    build_regime_capped_coverage_mask,
    compute_acceptance_scores,
    build_snapshot_feature_columns,
    build_time_context_columns,
    evaluate_high_confidence_policy,
    fit_dirichlet_calibrator,
    fit_flat_isotonic_calibrator,
    load_artifact_payload,
    normalized_entropy,
    search_acceptance_score_weights,
    resolve_execution_policy,
    save_training_payload,
    summarize_flat_post_calibration,
    top_two_margin,
)
from openclaw_trader.modules.quant_intelligence.support.snapshot_history import _load_tardis_open_interest_day
from openclaw_trader.modules.quant_intelligence.support.snapshot_history import BinanceSnapshotFeatureProvider
from openclaw_trader.modules.quant_intelligence.support.daily_macro_history import (
    FreeDailyMacroDerivativesProvider,
    _parse_coinalyze_history,
)
from openclaw_trader.shared.protocols import Candle


class QuantSupportTests(unittest.TestCase):
    def test_save_and_load_artifact_payload_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            artifact_root = Path(tempdir) / "perps"
            payload = {
                "meta": {"coin": "BTC", "horizon": "1h"},
                "regime": {"state_map": {"0": "bullish_trend"}},
                "classifier": {"constant_probs": np.asarray([0.1, 0.2, 0.7], dtype=np.float64)},
            }
            save_training_payload(
                artifact_root,
            coin="BTC",
            horizon="1h",
            payload=payload,
            report_payload={"status": "ok"},
            report_markdown="# ok\n",
            )
            loaded = load_artifact_payload(artifact_root, coin="BTC", horizon="1h")
            self.assertEqual(loaded["meta"]["coin"], "BTC")
            self.assertEqual(loaded["regime"]["state_map"]["0"], "bullish_trend")
            self.assertAlmostEqual(float(loaded["classifier"]["constant_probs"][2]), 0.7, places=6)

    def test_build_snapshot_feature_columns_includes_btc_relative_metrics(self) -> None:
        market = DataIngestBundle(
            trace_id="trace-1",
            market={
                "ETH": MarketSnapshotNormalized(
                    snapshot_id="eth-1",
                    coin="ETH",
                    product_id="ETH-PERP-INTX",
                    mark_price="2000",
                    funding_rate="0.01",
                    premium="0.02",
                    open_interest="100",
                    day_notional_volume="1000",
                ),
                "BTC": MarketSnapshotNormalized(
                    snapshot_id="btc-1",
                    coin="BTC",
                    product_id="BTC-PERP-INTX",
                    mark_price="60000",
                    funding_rate="0.005",
                    premium="0.01",
                    open_interest="150",
                    day_notional_volume="1400",
                ),
            },
            accounts={},
        )
        columns = build_snapshot_feature_columns(market=market, coin="ETH", length=40)
        self.assertIn("rel_market_funding_rate_vs_btc", columns)
        self.assertEqual(columns["rel_market_funding_rate_vs_btc"].shape[0], 40)

    def test_time_context_and_policy_resolution_helpers(self) -> None:
        candles = [
            Candle(start=1710000000 + (900 * idx), low=1, high=2, open=1.5, close=1.6, volume=10)
            for idx in range(8)
        ]
        columns = build_time_context_columns(candles)
        self.assertIn("time_hour_sin", columns)
        self.assertEqual(len(columns["time_hour_sin"]), len(candles))

        quant = QuantSettings()
        policy = resolve_execution_policy(
            quant,
            {
                "global": {"min_confidence": 0.5},
                "regimes": {"bullish_trend": {"policy": {"meta_min_confidence": 0.6}}},
            },
            "bullish_trend",
        )
        self.assertEqual(policy["min_confidence"], 0.5)
        self.assertEqual(policy["meta_min_confidence"], 0.6)

    def test_dirichlet_calibration_and_high_confidence_policy_helpers(self) -> None:
        probabilities = np.asarray(
            [
                [0.8, 0.1, 0.1],
                [0.1, 0.8, 0.1],
                [0.1, 0.2, 0.7],
                [0.4, 0.3, 0.3],
                [0.34, 0.33, 0.33],
            ],
            dtype=np.float64,
        )
        y_true = np.asarray([0, 1, 2, 0, 1], dtype=np.int32)
        calibrator = fit_dirichlet_calibrator(probabilities, y_true, random_seed=42)
        calibrated = apply_dirichlet_calibration(calibrator, probabilities)
        self.assertEqual(calibrated.shape, probabilities.shape)
        self.assertTrue(np.allclose(np.sum(calibrated, axis=1), 1.0))

        policy = build_high_confidence_policy(calibrated, y_true, target_coverage=0.4)
        accepted = evaluate_high_confidence_policy(calibrated, policy)
        self.assertGreaterEqual(accepted["coverage"], 0.2)
        self.assertEqual(top_two_margin(calibrated).shape[0], len(y_true))
        self.assertEqual(normalized_entropy(calibrated).shape[0], len(y_true))

        flat_calibrator = fit_flat_isotonic_calibrator(calibrated, y_true)
        post_calibrated = apply_flat_isotonic_rescale(flat_calibrator, calibrated)
        self.assertEqual(post_calibrated.shape, probabilities.shape)
        self.assertTrue(np.allclose(np.sum(post_calibrated, axis=1), 1.0))
        flat_report = summarize_flat_post_calibration(y_true, calibrated, post_calibrated, active=True)
        self.assertTrue(flat_report["active"])
        self.assertIn("before_flat_ece", flat_report)
        self.assertIn("after_flat_ece", flat_report)

    def test_acceptance_score_helpers_support_ranked_and_regime_capped_selection(self) -> None:
        probabilities = np.asarray(
            [
                [0.82, 0.10, 0.08],
                [0.78, 0.12, 0.10],
                [0.15, 0.20, 0.65],
                [0.20, 0.25, 0.55],
                [0.34, 0.33, 0.33],
            ],
            dtype=np.float64,
        )
        y_true = np.asarray([0, 0, 2, 2, 1], dtype=np.int32)
        trade_quality = np.asarray([0.9, 0.8, 0.85, 0.75, 0.4], dtype=np.float64)
        regime_labels = np.asarray(
            ["bearish_breakdown", "bearish_breakdown", "bullish_trend", "bullish_trend", "neutral_consolidation"],
            dtype=object,
        )

        scores, weights = compute_acceptance_scores(
            probabilities,
            trade_quality=trade_quality,
            components=[
                "calibrated_top_probability",
                "top_two_margin",
                "inverse_normalized_entropy",
                "meta_trade_quality_probability",
            ],
        )
        self.assertEqual(scores.shape[0], len(y_true))
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=4)

        capped = build_regime_capped_coverage_mask(
            scores,
            0.4,
            regime_labels=regime_labels,
            regime_coverage_caps={"bearish_breakdown": 0.2, "bullish_trend": 0.2, "neutral_consolidation": 0.2},
        )
        self.assertEqual(int(np.sum(capped)), 2)

        ranked = build_fixed_coverage_mask(
            probabilities,
            0.4,
            ranking_scores=scores,
            regime_labels=regime_labels,
            regime_coverage_caps={"bearish_breakdown": 0.2, "bullish_trend": 0.2, "neutral_consolidation": 0.2},
        )
        self.assertTrue(np.array_equal(capped, ranked))

        policy = build_high_confidence_policy(
            probabilities,
            y_true,
            target_coverage=0.4,
            trade_quality=trade_quality,
            regime_labels=regime_labels,
            score_components=[
                "calibrated_top_probability",
                "top_two_margin",
                "inverse_normalized_entropy",
                "meta_trade_quality_probability",
            ],
            regime_coverage_caps={"bearish_breakdown": 0.2, "bullish_trend": 0.2, "neutral_consolidation": 0.2},
        )
        accepted = evaluate_high_confidence_policy(
            probabilities,
            policy,
            trade_quality=trade_quality,
            regime_labels=regime_labels,
        )
        self.assertEqual(policy["mode"], "score_rank")
        self.assertGreaterEqual(accepted["coverage"], 0.2)
        self.assertEqual(accepted["score"].shape[0], len(y_true))

        best_weights, best_metrics = search_acceptance_score_weights(
            probabilities,
            y_true,
            np.asarray([0.03, 0.02, 0.05, 0.04, 0.0], dtype=np.float64),
            np.asarray([0.01, 0.01, 0.02, 0.01, 0.0], dtype=np.float64),
            components=[
                "calibrated_top_probability",
                "top_two_margin",
                "inverse_normalized_entropy",
                "meta_trade_quality_probability",
            ],
            target_coverage=0.4,
            trade_quality=trade_quality,
        )
        self.assertAlmostEqual(sum(best_weights.values()), 1.0, places=4)
        self.assertIn("precision", best_metrics)

    def test_panel_dataset_and_interaction_features_are_stable(self) -> None:
        candles = [
            Candle(start=1710000000 + (900 * idx), low=1, high=2, open=1.5, close=1.6 + (idx * 0.01), volume=10 + idx)
            for idx in range(64)
        ]
        prepared = prepare_series(candles, [3, 6, 12, 24])
        base_columns = build_time_context_columns(candles)
        base_columns.update(build_asset_indicator_columns(coin="BTC", length=len(candles)))
        base_columns.update(
            {
                "market_funding_abs": np.full(len(candles), 0.001, dtype=np.float64),
                "market_premium_abs": np.full(len(candles), 0.002, dtype=np.float64),
            }
        )
        interaction_columns = build_interaction_feature_columns(prepared, {**prepared.features, **base_columns})
        self.assertIn("jump_z_12", interaction_columns)
        self.assertEqual(interaction_columns["jump_z_12"].shape[0], len(candles))

        extra_columns = dict(base_columns)
        extra_columns.update(interaction_columns)
        extra_columns["regime_state"] = np.zeros(len(candles), dtype=np.float64)
        extra_columns["regime_confidence"] = np.ones(len(candles), dtype=np.float64)
        btc_dataset = build_supervised_dataset(
            candles,
            windows=[3, 6, 12, 24],
            horizon_bars=4,
            move_threshold_pct=0.001,
            extra_columns=extra_columns,
            coin_label="BTC",
            regime_state_map={"0": "bullish_trend"},
        )
        eth_dataset = build_supervised_dataset(
            candles,
            windows=[3, 6, 12, 24],
            horizon_bars=4,
            move_threshold_pct=0.001,
            extra_columns=extra_columns,
            coin_label="ETH",
            regime_state_map={"0": "bullish_trend"},
        )
        combined = combine_supervised_datasets({"BTC": btc_dataset, "ETH": eth_dataset})
        self.assertTrue(np.all(np.diff(combined.timestamps) >= 0))
        self.assertEqual(set(combined.coin_labels.tolist()), {"BTC", "ETH"})
        self.assertEqual(combined.regime_labels[0], "bullish_trend")
        self.assertIn("jump_z_12", combined.feature_names)

    def test_long_horizon_and_adaptive_threshold_features_are_stable(self) -> None:
        candles = [
            Candle(
                start=1710000000 + (900 * idx),
                low=1 + (idx * 0.01),
                high=2 + (idx * 0.01),
                open=1.5 + (idx * 0.01),
                close=1.6 + (idx * 0.01),
                volume=100 + idx,
            )
            for idx in range(256)
        ]
        prepared = prepare_series(candles, [3, 6, 12, 24, 48])
        long_features = build_long_horizon_feature_columns(prepared)
        self.assertIn("ret_192", long_features)
        self.assertEqual(long_features["vol_192"].shape[0], len(candles))

        thresholds, diagnostics = build_adaptive_move_thresholds(
            prepared,
            base_threshold_pct=0.0025,
            horizon_bars=48,
            volatility_window=192,
            floor_multiplier=0.5,
            cap_multiplier=3.0,
        )
        self.assertEqual(thresholds.shape[0], len(candles))
        self.assertTrue(np.all(np.isfinite(thresholds)))
        self.assertGreaterEqual(float(np.min(thresholds)), 0.00125)
        self.assertIn("mean_threshold", diagnostics)

    def test_load_tardis_open_interest_day_uses_latest_event_in_each_bucket(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "ETHUSDT.csv.gz"
            rows = [
                {"timestamp": "1710000000000000", "open_interest": "100.5"},
                {"timestamp": "1710000300000000", "open_interest": "101.5"},
                {"timestamp": "1710000900000000", "open_interest": "110.0"},
                {"timestamp": "1710000901000000", "open_interest": "111.0"},
                {"timestamp": "1710000902000000", "open_interest": ""},
            ]
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                handle.write("timestamp,open_interest\n")
                for row in rows:
                    handle.write(f"{row['timestamp']},{row['open_interest']}\n")

            payload = _load_tardis_open_interest_day(path, interval_ms=900_000)
            self.assertEqual(len(payload), 2)
            self.assertEqual(payload[1_710_000_000_000], 101.5)
            self.assertEqual(payload[1_710_000_900_000], 111.0)

    def test_backfill_candles_window_populates_cache_and_summary(self) -> None:
        class FakeClient:
            def __init__(self, candles: list[Candle]) -> None:
                self._candles = candles
                self.calls: list[tuple[int, int, str, int | None]] = []

            def get_public_candles(
                self,
                product_id: str,
                *,
                start: int,
                end: int,
                granularity: str,
                limit: int | None = None,
            ) -> list[Candle]:
                self.calls.append((start, end, granularity, limit))
                return [candle for candle in self._candles if start <= candle.start < end]

        start_at = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        end_at = start_at + timedelta(hours=1)
        candles = [
            Candle(
                start=int((start_at + timedelta(minutes=15 * idx)).timestamp()),
                low=100 + idx,
                high=101 + idx,
                open=100.5 + idx,
                close=100.75 + idx,
                volume=10 + idx,
            )
            for idx in range(4)
        ]
        client = FakeClient(candles)
        quant = QuantSettings(interval="15m")
        with tempfile.TemporaryDirectory() as tempdir:
            cache_dir = Path(tempdir)
            summary = backfill_candles_window(
                client,
                coin="ETH",
                quant=quant,
                start_at=start_at,
                end_at=end_at,
                cache_dir=cache_dir,
            )
            cache_file = cache_dir / "ETH_15m.joblib"
            self.assertTrue(cache_file.exists())
            cached = joblib.load(cache_file)
            self.assertEqual(len(cached), 4)
            self.assertEqual(summary["candle_expected_bars"], 4.0)
            self.assertEqual(summary["candle_observed_bars"], 4.0)
            self.assertEqual(summary["candle_missing_ratio"], 0.0)
            self.assertTrue(client.calls)

            second_client = FakeClient(candles)
            second_summary = backfill_candles_window(
                second_client,
                coin="ETH",
                quant=quant,
                start_at=start_at,
                end_at=end_at,
                cache_dir=cache_dir,
            )
            self.assertEqual(second_summary["candle_observed_bars"], 4.0)
            self.assertEqual(second_client.calls, [])

    def test_tardis_without_key_only_attempts_monthly_first_day(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            provider = BinanceSnapshotFeatureProvider(cache_dir=Path(tempdir), tardis_api_key=None)
            attempted_days: list[int] = []

            def fake_download(*, symbol: str, day: datetime, destination: Path) -> None:
                attempted_days.append(day.day)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with gzip.open(destination, "wt", encoding="utf-8") as handle:
                    handle.write("timestamp,open_interest\n")
                    handle.write(f"{int(day.timestamp() * 1_000_000)},123.45\n")

            provider._download_tardis_file = fake_download  # type: ignore[method-assign]
            rows = provider._load_or_fetch_tardis_open_interest_days(
                coin="BTC",
                symbol="BTCUSDT",
                interval="15m",
                start_ms=int(datetime(2025, 1, 1, tzinfo=UTC).timestamp() * 1000),
                end_ms=int(datetime(2025, 1, 3, tzinfo=UTC).timestamp() * 1000),
            )
            self.assertEqual(attempted_days, [1])
            self.assertTrue(rows)

    def test_parse_coinalyze_history_extracts_requested_metric(self) -> None:
        payload = [
            {
                "symbol": "ETHUSDT_PERP.A",
                "history": [
                    {"t": 1710460800, "c": 1234.5, "r": 1.12},
                    {"t": 1710547200, "c": 1250.0, "r": 1.08},
                ],
            }
        ]
        open_interest = _parse_coinalyze_history(payload, value_key="c")
        ratio = _parse_coinalyze_history(payload, value_key="r")
        self.assertEqual(open_interest[1710460800000], 1234.5)
        self.assertEqual(ratio[1710547200000], 1.08)

    def test_daily_macro_provider_builds_slow_features_without_coinalyze_key(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            cache_root = Path(tempdir)
            normalized_root = cache_root / "normalized"
            normalized_root.mkdir(parents=True, exist_ok=True)
            raw_tardis_root = cache_root / "raw" / "tardis" / "binance-futures" / "derivative_ticker"
            base_day = datetime(2026, 3, 1, tzinfo=UTC)

            snapshot_payload = {
                "funding_rates": {},
                "premiums": {},
                "quote_volumes": {},
                "open_interest": {},
            }
            for day_offset in range(12):
                day = base_day + timedelta(days=day_offset)
                ts_ms = int((day + timedelta(hours=23, minutes=45)).timestamp() * 1000)
                snapshot_payload["funding_rates"][ts_ms] = 0.0005 + (0.00001 * day_offset)
                snapshot_payload["premiums"][ts_ms] = 0.001 + (0.00002 * day_offset)
                snapshot_payload["quote_volumes"][ts_ms] = 1_000_000 + (5_000 * day_offset)
                snapshot_payload["open_interest"][ts_ms] = 10_000_000 + (50_000 * day_offset)
            joblib.dump(snapshot_payload, normalized_root / "ETH_15m_hybrid_snapshot.joblib")

            for anchor_day, value in (
                (datetime(2026, 2, 1, tzinfo=UTC), 9_500_000.0),
                (datetime(2026, 3, 1, tzinfo=UTC), 10_000_000.0),
            ):
                anchor_path = raw_tardis_root / f"{anchor_day:%Y}" / f"{anchor_day:%m}" / f"{anchor_day:%d}" / "ETHUSDT.csv.gz"
                anchor_path.parent.mkdir(parents=True, exist_ok=True)
                with gzip.open(anchor_path, "wt", encoding="utf-8") as handle:
                    handle.write("timestamp,local_timestamp,exchange,symbol,type,contract_type,open_interest\n")
                    handle.write(
                        f"{int((anchor_day + timedelta(hours=23)).timestamp() * 1_000_000)},{int(anchor_day.timestamp() * 1_000_000)},binance-futures,ETHUSDT,trade,perpetual,{value}\n"
                    )

            candles = [
                Candle(
                    start=int((base_day + timedelta(minutes=15 * idx)).timestamp()),
                    low=1.0,
                    high=2.0,
                    open=1.5,
                    close=1.6,
                    volume=100.0,
                )
                for idx in range(96 * 5)
            ]
            provider = FreeDailyMacroDerivativesProvider(cache_dir=cache_root, coinalyze_enabled=True, coinalyze_api_key=None)
            provider._download_tardis_monthly_file = lambda **kwargs: None  # type: ignore[method-assign]
            payload = provider.build_feature_payload(coin="ETH", candles=candles, quant=QuantSettings())
            provider.close()

            self.assertIn("daily_oi_change_7", payload.columns)
            self.assertIn("monthly_oi_anchor_gap", payload.columns)
            self.assertIn("days_since_monthly_oi_anchor", payload.columns)
            self.assertEqual(payload.columns["daily_oi_change_7"].shape[0], len(candles))
            self.assertIn("coinalyze_enabled", payload.quality_summary)
            self.assertFalse(payload.quality_summary["coinalyze_enabled"])
            self.assertIn("tardis_monthly_anchor_summary", payload.quality_summary)


if __name__ == "__main__":
    unittest.main()
