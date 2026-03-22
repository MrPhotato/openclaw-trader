from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import benchmark_quant_intelligence as bench


BASELINE_PROFILE = "baseline_1h"
HORIZONS = ("1h",)
HISTORY_VALUES = (1500, 3000, 6000)
THRESHOLD_VALUES = (0.0015, 0.0020, 0.0025)
CALIBRATION_ECE_TRIGGER = 0.05


def _all_coin_history_overrides(history_bars: int) -> dict[str, int]:
    return {f"{coin}:1h": int(history_bars) for coin in bench.COINS}


def _all_coin_threshold_overrides(threshold: float) -> dict[str, float]:
    return {f"{coin}:1h": float(threshold) for coin in bench.COINS}


def _settings_for(
    runtime_root: Path,
    *,
    history_bars: int,
    threshold: float,
    calibration_mode_by_coin_horizon: dict[str, str] | None = None,
) -> Any:
    return bench.build_benchmark_settings(
        runtime_root,
        forecast_horizons={"1h": 4},
        training_history_bars_overrides_by_coin_horizon=_all_coin_history_overrides(history_bars),
        target_move_threshold_pct_overrides_by_coin_horizon=_all_coin_threshold_overrides(threshold),
        probability_calibration_mode_by_coin_horizon=calibration_mode_by_coin_horizon or {},
        daily_macro_features_enabled=False,
        history_backfill_days=120,
    )


def _payload(summary: dict[str, Any], coin: str) -> dict[str, Any]:
    return summary["coins"][coin]["1h"]


def _precision(summary: dict[str, Any], coin: str, bucket: str = "30%") -> float:
    return float(
        _payload(summary, coin)
        .get("high_confidence_metrics", {})
        .get("precision_at_coverage", {})
        .get(bucket, {})
        .get("precision", 0.0)
    )


def _coverage(summary: dict[str, Any], coin: str, bucket: str = "30%") -> float:
    return float(
        _payload(summary, coin)
        .get("high_confidence_metrics", {})
        .get("precision_at_coverage", {})
        .get(bucket, {})
        .get("achieved_coverage", 0.0)
    )


def _ece(summary: dict[str, Any], coin: str) -> float:
    return float(_payload(summary, coin).get("validation_ece", 0.0))


def _delta_report(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    by_coin: dict[str, Any] = {}
    current_precisions: list[float] = []
    baseline_precisions: list[float] = []
    current_eces: list[float] = []
    baseline_eces: list[float] = []
    coverages: list[float] = []
    non_negative_coins = 0

    for coin in bench.COINS:
        current_precision = _precision(current, coin)
        baseline_precision = _precision(baseline, coin)
        current_ece = _ece(current, coin)
        baseline_ece = _ece(baseline, coin)
        current_coverage = _coverage(current, coin)
        baseline_coverage = _coverage(baseline, coin)
        delta_precision = current_precision - baseline_precision
        if delta_precision >= 0.0:
            non_negative_coins += 1
        by_coin[coin] = {
            "current_precision_30": round(current_precision, 4),
            "baseline_precision_30": round(baseline_precision, 4),
            "delta_precision_30": round(delta_precision, 4),
            "current_coverage_30": round(current_coverage, 4),
            "baseline_coverage_30": round(baseline_coverage, 4),
            "current_ece": round(current_ece, 6),
            "baseline_ece": round(baseline_ece, 6),
            "delta_ece": round(current_ece - baseline_ece, 6),
        }
        current_precisions.append(current_precision)
        baseline_precisions.append(baseline_precision)
        current_eces.append(current_ece)
        baseline_eces.append(baseline_ece)
        coverages.append(current_coverage)

    current_avg_precision = sum(current_precisions) / max(len(current_precisions), 1)
    baseline_avg_precision = sum(baseline_precisions) / max(len(baseline_precisions), 1)
    current_avg_ece = sum(current_eces) / max(len(current_eces), 1)
    baseline_avg_ece = sum(baseline_eces) / max(len(baseline_eces), 1)
    ece_improvement_ratio = 0.0 if baseline_avg_ece <= 0 else 1.0 - (current_avg_ece / baseline_avg_ece)
    min_current_coverage = min(coverages) if coverages else 0.0
    max_current_coverage = max(coverages) if coverages else 0.0
    avg_precision_delta = current_avg_precision - baseline_avg_precision

    return {
        "by_coin": by_coin,
        "headline": {
            "avg_1h_precision_30_delta": round(avg_precision_delta, 4),
            "avg_current_ece": round(current_avg_ece, 6),
            "avg_baseline_ece": round(baseline_avg_ece, 6),
            "ece_improvement_ratio": round(ece_improvement_ratio, 4),
            "min_current_coverage_30": round(min_current_coverage, 4),
            "max_current_coverage_30": round(max_current_coverage, 4),
            "non_negative_coin_count": non_negative_coins,
        },
    }


def _profile_checks(summary: dict[str, Any], *, baseline_summary: dict[str, Any], dev_summary: dict[str, Any]) -> dict[str, bool]:
    vs_dev = _delta_report(summary, dev_summary)
    return {
        "avg_1h_precision_30_delta_gte_2pp": float(vs_dev["headline"]["avg_1h_precision_30_delta"]) >= 0.02,
        "non_negative_coin_count_gte_2": int(vs_dev["headline"]["non_negative_coin_count"]) >= 2,
        "btc_not_worse_than_minus_1pp": float(vs_dev["by_coin"]["BTC"]["delta_precision_30"]) >= -0.01,
        "ece_improvement_gte_80pct": float(vs_dev["headline"]["ece_improvement_ratio"]) >= 0.80,
        "coverage_30_between_25_and_35pct": (
            float(vs_dev["headline"]["min_current_coverage_30"]) >= 0.25
            and float(vs_dev["headline"]["max_current_coverage_30"]) <= 0.35
        ),
    }


def _profile_is_viable(summary: dict[str, Any], *, baseline_summary: dict[str, Any], dev_summary: dict[str, Any]) -> bool:
    return all(_profile_checks(summary, baseline_summary=baseline_summary, dev_summary=dev_summary).values())


def _profile_sort_key(summary: dict[str, Any], *, baseline_summary: dict[str, Any], dev_summary: dict[str, Any]) -> tuple[float, float, float, float]:
    vs_dev = _delta_report(summary, dev_summary)
    return (
        float(vs_dev["headline"]["avg_1h_precision_30_delta"]),
        float(vs_dev["headline"]["non_negative_coin_count"]),
        float(vs_dev["headline"]["ece_improvement_ratio"]),
        float(vs_dev["by_coin"]["BTC"]["delta_precision_30"]),
    )


def _profile_result(
    summary: dict[str, Any],
    *,
    baseline_summary: dict[str, Any],
    baseline_name: str,
    vs_baseline: dict[str, Any] | None,
    vs_dev: dict[str, Any],
    dev_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "vs_codex_dev": vs_dev,
        "vs_baseline_1h": vs_baseline,
        "checks": _profile_checks(summary, baseline_summary=baseline_summary, dev_summary=dev_summary),
        "baseline_profile": baseline_name,
        "coins": {
            coin: {
                "precision_at_coverage": _payload(summary, coin).get("high_confidence_metrics", {}).get("precision_at_coverage", {}),
                "validation_ece": _payload(summary, coin).get("validation_ece"),
                "validation_classwise_ece": _payload(summary, coin).get("validation_classwise_ece", {}),
                "accepted_slice_distribution": _payload(summary, coin).get("label_diagnostics", {}).get("high_confidence_slice", {}).get("distribution", {}),
                "label_threshold_pct": _payload(summary, coin).get("label_threshold_pct"),
                "probability_calibration_mode": _payload(summary, coin).get("probability_calibration_mode", "dirichlet"),
                "history_bars": _payload(summary, coin).get("history_bars"),
            }
            for coin in bench.COINS
        },
    }


def _coins_requiring_post_calibration(summary: dict[str, Any]) -> list[str]:
    coins: list[str] = []
    for coin in bench.COINS:
        if _ece(summary, coin) > CALIBRATION_ECE_TRIGGER:
            coins.append(coin)
    return coins


def main() -> None:
    parser = argparse.ArgumentParser(description="Focused 1h fact-layer benchmark on top of the current QI pipeline.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--shared-cache-root", type=Path, required=True)
    parser.add_argument("--baseline-json", type=Path, default=None)
    args = parser.parse_args()

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    shared_cache_root = args.shared_cache_root

    baseline_settings = _settings_for(
        output_dir / BASELINE_PROFILE,
        history_bars=1500,
        threshold=0.0025,
    )
    bench.prepare_history_bundle(shared_cache_root, settings=baseline_settings)

    baseline_current = bench.run_current_benchmark(
        output_dir,
        profile=BASELINE_PROFILE,
        settings=baseline_settings,
        shared_cache_root=shared_cache_root,
        horizons=HORIZONS,
    )
    if args.baseline_json is not None:
        baseline_dev = json.loads(args.baseline_json.read_text())
    else:
        baseline_dev = bench.run_codex_dev_benchmark(
            output_dir,
            manifest_file=bench.history_manifest_path(shared_cache_root),
            horizons=HORIZONS,
        )

    current_profiles: dict[str, dict[str, Any]] = {BASELINE_PROFILE: baseline_current}

    history_candidates = [value for value in HISTORY_VALUES if value != 1500]
    for history_bars in history_candidates:
        profile = f"oneh_history_{history_bars}"
        current_profiles[profile] = bench.run_current_benchmark(
            output_dir,
            profile=profile,
            settings=_settings_for(output_dir / profile, history_bars=history_bars, threshold=0.0025),
            shared_cache_root=shared_cache_root,
            horizons=HORIZONS,
        )

    best_history_profile = max(
        current_profiles,
        key=lambda name: _profile_sort_key(
            current_profiles[name],
            baseline_summary=baseline_current,
            dev_summary=baseline_dev,
        ),
    )
    best_history_summary = current_profiles[best_history_profile]
    best_history_bars = int(_payload(best_history_summary, "BTC").get("history_bars", 1500))

    threshold_profiles: list[str] = []
    for threshold in THRESHOLD_VALUES:
        profile = f"oneh_threshold_{str(threshold).replace('.', 'p')}"
        current_profiles[profile] = bench.run_current_benchmark(
            output_dir,
            profile=profile,
            settings=_settings_for(output_dir / profile, history_bars=best_history_bars, threshold=threshold),
            shared_cache_root=shared_cache_root,
            horizons=HORIZONS,
        )
        threshold_profiles.append(profile)

    best_threshold_profile = max(
        threshold_profiles,
        key=lambda name: _profile_sort_key(
            current_profiles[name],
            baseline_summary=baseline_current,
            dev_summary=baseline_dev,
        ),
    )
    best_threshold_summary = current_profiles[best_threshold_profile]

    calibration_candidates = _coins_requiring_post_calibration(best_threshold_summary)
    if calibration_candidates:
        calibration_profile = f"{best_threshold_profile}_postcal"
        calibration_overrides = {f"{coin}:1h": "flat_isotonic_rescale" for coin in calibration_candidates}
        current_profiles[calibration_profile] = bench.run_current_benchmark(
            output_dir,
            profile=calibration_profile,
            settings=_settings_for(
                output_dir / calibration_profile,
                history_bars=best_history_bars,
                threshold=float(_payload(best_threshold_summary, "BTC").get("label_threshold_pct", 0.0025)),
                calibration_mode_by_coin_horizon=calibration_overrides,
            ),
            shared_cache_root=shared_cache_root,
            horizons=HORIZONS,
        )

    deltas_vs_dev = {name: _delta_report(summary, baseline_dev) for name, summary in current_profiles.items()}
    deltas_vs_baseline = {
        name: _delta_report(summary, baseline_current)
        for name, summary in current_profiles.items()
        if name != BASELINE_PROFILE
    }

    viable_profiles = [
        name
        for name, summary in current_profiles.items()
        if name != BASELINE_PROFILE and _profile_is_viable(summary, baseline_summary=baseline_current, dev_summary=baseline_dev)
    ]
    selected_profile = (
        max(
            viable_profiles,
            key=lambda name: _profile_sort_key(
                current_profiles[name],
                baseline_summary=baseline_current,
                dev_summary=baseline_dev,
            ),
        )
        if viable_profiles
        else BASELINE_PROFILE
    )

    report = {
        "baseline_profile": BASELINE_PROFILE,
        "selected_profile": selected_profile,
        "history_bundle_manifest": json.loads(bench.history_manifest_path(shared_cache_root).read_text()),
        "profiles": {
            name: _profile_result(
                summary,
                baseline_summary=baseline_current,
                baseline_name=BASELINE_PROFILE,
                vs_baseline=None if name == BASELINE_PROFILE else deltas_vs_baseline.get(name),
                vs_dev=deltas_vs_dev[name],
                dev_summary=baseline_dev,
            )
            for name, summary in current_profiles.items()
        },
    }
    report_path = output_dir / "oneh_focused_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"report": str(report_path), "selected_profile": selected_profile}, ensure_ascii=False))


if __name__ == "__main__":
    main()
