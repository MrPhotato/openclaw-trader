from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch


def _load_script_module(filename: str, module_name: str):
    script_path = Path(__file__).resolve().parents[1] / "scripts" / filename
    sys.path.insert(0, str(script_path.parent))
    try:
        spec = importlib.util.spec_from_file_location(module_name, script_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"failed to load spec for {script_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def _summary(*, eth_precision: float, eth_ece: float, eth_flat_ece: float, calibration_mode: str = "dirichlet") -> dict:
    return {
        "coins": {
            "ETH": {
                "4h": {
                    "label_threshold_pct": 0.0025,
                    "probability_calibration_mode": calibration_mode,
                    "validation_ece": eth_ece,
                    "validation_classwise_ece": {"flat": eth_flat_ece},
                    "classwise_ece_after_post_calibration": {"flat": eth_flat_ece},
                    "high_confidence_metrics": {
                        "precision_at_coverage": {
                            "30%": {"precision": eth_precision},
                        }
                    },
                }
            }
        }
    }


def _delta_report(
    *,
    avg_12h_delta: float,
    btc_precision: float = 0.0,
    sol_precision: float = 0.0,
) -> dict:
    return {
        "by_coin": {
            "BTC": {"4h": {"delta_precision_30": btc_precision}},
            "ETH": {"4h": {"delta_precision_30": 0.0}},
            "SOL": {"4h": {"delta_precision_30": sol_precision}},
        },
        "headline": {"avg_12h_precision_30_delta": avg_12h_delta},
    }


def _benchmark_summary(
    *,
    btc4: float = 0.50,
    eth4: float = 0.40,
    sol4: float = 0.41,
    btc12: float = 0.38,
    eth12: float = 0.40,
    sol12: float = 0.41,
    ece: float = 0.02,
    coverage: float = 0.30,
) -> dict:
    def _horizon_payload(precision: float) -> dict:
        return {
            "validation_ece": ece,
            "validation_brier": 0.12,
            "validation_log_loss": 0.35,
            "high_confidence_metrics": {
                "precision_at_coverage": {
                    "30%": {"precision": precision, "coverage": coverage},
                }
            },
        }

    return {
        "coins": {
            "BTC": {"4h": _horizon_payload(btc4), "12h": _horizon_payload(btc12)},
            "ETH": {"4h": _horizon_payload(eth4), "12h": _horizon_payload(eth12)},
            "SOL": {"4h": _horizon_payload(sol4), "12h": _horizon_payload(sol12)},
        }
    }


def _benchmark_summary_1h(
    *,
    btc1: float = 0.40,
    eth1: float = 0.41,
    sol1: float = 0.42,
    ece: float = 0.02,
    coverage: float = 0.30,
) -> dict:
    def _horizon_payload(precision: float) -> dict:
        return {
            "validation_ece": ece,
            "validation_brier": 0.12,
            "validation_log_loss": 0.35,
            "label_threshold_pct": 0.0025,
            "probability_calibration_mode": "dirichlet",
            "history_bars": 1500,
            "label_diagnostics": {"high_confidence_slice": {"distribution": {"short": 0.3, "flat": 0.4, "long": 0.3}}},
            "high_confidence_metrics": {
                "precision_at_coverage": {
                    "30%": {"precision": precision, "achieved_coverage": coverage},
                }
            },
        }

    return {
        "coins": {
            "BTC": {"1h": _horizon_payload(btc1)},
            "ETH": {"1h": _horizon_payload(eth1)},
            "SOL": {"1h": _horizon_payload(sol1)},
        }
    }


class FocusedBenchmarkScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.focused = _load_script_module("benchmark_quant_eth4h_focused.py", "qi_benchmark_eth4h_focused_test")
        cls.focused_12h = _load_script_module("benchmark_quant_12h_focused.py", "qi_benchmark_12h_focused_test")
        cls.focused_1h = _load_script_module("benchmark_quant_1h_focused.py", "qi_benchmark_1h_focused_test")
        cls.history_bundle = _load_script_module("_quant_history_bundle.py", "qi_history_bundle_test")

    def test_profile_is_viable_requires_signal_quality_constraints(self) -> None:
        baseline = _summary(eth_precision=0.4819, eth_ece=0.023162, eth_flat_ece=0.024552)
        candidate = _summary(eth_precision=0.491, eth_ece=0.0259, eth_flat_ece=0.02, calibration_mode="flat_isotonic_rescale")
        vs_baseline = _delta_report(avg_12h_delta=0.11, btc_precision=-0.009, sol_precision=0.0)
        vs_dev = _delta_report(avg_12h_delta=0.11, btc_precision=0.0, sol_precision=0.0)

        self.assertTrue(
            self.focused._profile_is_viable(
                candidate,
                baseline_summary=baseline,
                vs_baseline=vs_baseline,
                vs_dev=vs_dev,
            )
        )

        bad_ece = _summary(eth_precision=0.491, eth_ece=0.0265, eth_flat_ece=0.02)
        self.assertFalse(
            self.focused._profile_is_viable(
                bad_ece,
                baseline_summary=baseline,
                vs_baseline=vs_baseline,
                vs_dev=vs_dev,
            )
        )

        no_flat_improvement = _summary(eth_precision=0.491, eth_ece=0.0259, eth_flat_ece=0.03)
        self.assertFalse(
            self.focused._profile_is_viable(
                no_flat_improvement,
                baseline_summary=baseline,
                vs_baseline=vs_baseline,
                vs_dev=vs_dev,
            )
        )

    def test_profile_sort_prefers_precision_then_lower_ece(self) -> None:
        baseline = _summary(eth_precision=0.4819, eth_ece=0.023162, eth_flat_ece=0.024552)
        higher_precision = _summary(eth_precision=0.501, eth_ece=0.0255, eth_flat_ece=0.022)
        lower_ece = _summary(eth_precision=0.495, eth_ece=0.0215, eth_flat_ece=0.018)
        vs_baseline = _delta_report(avg_12h_delta=0.11, btc_precision=0.0, sol_precision=0.0)
        vs_dev = _delta_report(avg_12h_delta=0.11, btc_precision=0.0, sol_precision=0.0)

        self.assertGreater(
            self.focused._profile_sort_key(
                higher_precision,
                baseline_summary=baseline,
                vs_baseline=vs_baseline,
                vs_dev=vs_dev,
            ),
            self.focused._profile_sort_key(
                lower_ece,
                baseline_summary=baseline,
                vs_baseline=vs_baseline,
                vs_dev=vs_dev,
            ),
        )

    def test_12h_profile_viability_requires_both_eth_and_sol_not_negative(self) -> None:
        baseline = _benchmark_summary(btc12=0.36, eth12=0.36, sol12=0.36)
        candidate_good = _benchmark_summary(btc12=0.40, eth12=0.41, sol12=0.42, ece=0.002)
        candidate_bad_sol = _benchmark_summary(btc12=0.40, eth12=0.41, sol12=0.34, ece=0.002)
        dev = _benchmark_summary(btc12=0.35, eth12=0.35, sol12=0.35, ece=0.03)

        self.assertTrue(
            self.focused_12h._profile_is_viable(
                candidate_good,
                baseline_summary=baseline,
                dev_summary=dev,
            )
        )
        self.assertFalse(
            self.focused_12h._profile_is_viable(
                candidate_bad_sol,
                baseline_summary=baseline,
                dev_summary=dev,
            )
        )

    def test_1h_profile_viability_requires_precision_and_calibration_constraints(self) -> None:
        baseline = _benchmark_summary_1h(btc1=0.38, eth1=0.39, sol1=0.40, ece=0.10)
        dev = _benchmark_summary_1h(btc1=0.37, eth1=0.38, sol1=0.39, ece=0.20)
        candidate_good = _benchmark_summary_1h(btc1=0.40, eth1=0.41, sol1=0.42, ece=0.02)
        candidate_bad_btc = _benchmark_summary_1h(btc1=0.35, eth1=0.41, sol1=0.42, ece=0.02)
        candidate_bad_ece = _benchmark_summary_1h(btc1=0.40, eth1=0.41, sol1=0.42, ece=0.05)

        self.assertTrue(
            self.focused_1h._profile_is_viable(
                candidate_good,
                baseline_summary=baseline,
                dev_summary=dev,
            )
        )
        self.assertFalse(
            self.focused_1h._profile_is_viable(
                candidate_bad_btc,
                baseline_summary=baseline,
                dev_summary=dev,
            )
        )
        self.assertFalse(
            self.focused_1h._profile_is_viable(
                candidate_bad_ece,
                baseline_summary=baseline,
                dev_summary=dev,
            )
        )

    def test_1h_profile_sort_prefers_precision_then_non_negative_count(self) -> None:
        baseline = _benchmark_summary_1h(btc1=0.38, eth1=0.39, sol1=0.40, ece=0.10)
        dev = _benchmark_summary_1h(btc1=0.37, eth1=0.38, sol1=0.39, ece=0.20)
        higher_precision = _benchmark_summary_1h(btc1=0.42, eth1=0.43, sol1=0.44, ece=0.02)
        lower_precision = _benchmark_summary_1h(btc1=0.40, eth1=0.41, sol1=0.42, ece=0.01)

        self.assertGreater(
            self.focused_1h._profile_sort_key(
                higher_precision,
                baseline_summary=baseline,
                dev_summary=dev,
            ),
            self.focused_1h._profile_sort_key(
                lower_precision,
                baseline_summary=baseline,
                dev_summary=dev,
            ),
        )

    def test_prepare_history_bundle_writes_manifest(self) -> None:
        class FakeClient:
            def close(self) -> None:
                return None

        class FakeProvider:
            def __init__(self) -> None:
                self.closed = False

            def backfill_history(self, *, coin: str, interval: str, start_ms: int, end_ms: int, quant):
                return {
                    "coin": coin,
                    "interval": interval,
                    "start_ms": float(start_ms),
                    "end_ms": float(end_ms),
                    "open_interest_missing_ratio": 0.0,
                }

            def close(self) -> None:
                self.closed = True

        class FakeDailyMacroProvider:
            def __init__(self) -> None:
                self.closed = False

            def backfill_history(self, *, coin: str, interval: str, start_ms: int, end_ms: int, quant):
                return {
                    "coinalyze_enabled": False,
                    "daily_oi_missing_ratio": 1.0,
                    "tardis_monthly_anchor_summary": {"rows": 1},
                }

            def close(self) -> None:
                self.closed = True

        fake_provider = FakeProvider()
        fake_daily_provider = FakeDailyMacroProvider()

        with tempfile.TemporaryDirectory() as tempdir:
            shared_root = Path(tempdir)
            settings = self.focused._settings_for(shared_root / "runtime", threshold=0.0025, calibration_mode="dirichlet")
            fake_end = datetime(2026, 3, 17, 12, 0, tzinfo=UTC)

            with patch.object(self.history_bundle, "PublicCoinbaseCandleClient", return_value=FakeClient()), patch.object(
                self.history_bundle,
                "build_snapshot_feature_provider",
                return_value=fake_provider,
            ), patch.object(
                self.history_bundle,
                "build_daily_macro_feature_provider",
                return_value=fake_daily_provider,
            ), patch.object(
                self.history_bundle,
                "backfill_candles_window",
                side_effect=lambda *args, coin, **kwargs: {
                    "candle_start_ts": 1.0,
                    "candle_end_ts": 2.0,
                    "candle_expected_bars": 3.0,
                    "candle_observed_bars": 3.0,
                    "candle_missing_ratio": 0.0,
                    "coin": coin,
                },
            ):
                manifest = self.history_bundle.prepare_history_bundle(shared_root, settings=settings, end_at=fake_end)

            manifest_file = self.history_bundle.manifest_path(shared_root)
            self.assertTrue(manifest_file.exists())
            loaded = json.loads(manifest_file.read_text())
            self.assertEqual(loaded["window_end_utc"], manifest["window_end_utc"])
            self.assertEqual(set(loaded["coins"].keys()), {"BTC", "ETH", "SOL"})
            self.assertTrue(fake_provider.closed)
            self.assertTrue(fake_daily_provider.closed)


if __name__ == "__main__":
    unittest.main()
