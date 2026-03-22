from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import benchmark_quant_intelligence as bench


DEFAULT_THRESHOLD_CANDIDATES = list(bench.ETH4H_SIGNAL_THRESHOLD_CANDIDATES)
BASELINE_PROFILE = "baseline_long_history"


def _settings_for(
    runtime_root: Path,
    *,
    threshold: float,
    calibration_mode: str,
) -> Any:
    return bench.build_benchmark_settings(
        runtime_root,
        target_move_threshold_pct_overrides_by_coin_horizon={"ETH:4h": float(threshold)},
        probability_calibration_mode_by_coin_horizon={"ETH:4h": calibration_mode},
    )


def _eth4h_payload(summary: dict[str, Any]) -> dict[str, Any]:
    return summary["coins"]["ETH"]["4h"]


def _flat_class_ece(summary: dict[str, Any]) -> float:
    payload = _eth4h_payload(summary)
    return float(
        payload.get("classwise_ece_after_post_calibration", {}).get(
            "flat",
            payload.get("validation_classwise_ece", {}).get("flat", 0.0),
        )
    )


def _eth4h_precision_30(summary: dict[str, Any]) -> float:
    return float(
        _eth4h_payload(summary)
        .get("high_confidence_metrics", {})
        .get("precision_at_coverage", {})
        .get("30%", {})
        .get("precision", 0.0)
    )


def _eth4h_validation_ece(summary: dict[str, Any]) -> float:
    return float(_eth4h_payload(summary).get("validation_ece", 0.0))


def _profile_checks(
    summary: dict[str, Any],
    *,
    baseline_summary: dict[str, Any],
    vs_baseline: dict | None,
    vs_dev: dict | None,
) -> dict[str, bool]:
    if not vs_baseline or not vs_dev:
        return {
            "eth_precision_30_gte_0_49": False,
            "eth_ece_lte_0_026": False,
            "eth_flat_class_ece_improved": False,
            "btc_not_worse_than_minus_1pp": False,
            "sol_not_worse_than_minus_1pp": False,
            "avg_12h_precision_30_delta_gte_10pp": False,
        }
    eth_precision = _eth4h_precision_30(summary)
    eth_ece = _eth4h_validation_ece(summary)
    eth_flat_ece = _flat_class_ece(summary)
    baseline_flat_ece = _flat_class_ece(baseline_summary)
    return {
        "eth_precision_30_gte_0_49": eth_precision >= 0.49,
        "eth_ece_lte_0_026": eth_ece <= 0.026,
        "eth_flat_class_ece_improved": eth_flat_ece < baseline_flat_ece,
        "btc_not_worse_than_minus_1pp": float(vs_baseline["by_coin"]["BTC"]["4h"]["delta_precision_30"]) >= -0.01,
        "sol_not_worse_than_minus_1pp": float(vs_baseline["by_coin"]["SOL"]["4h"]["delta_precision_30"]) >= -0.01,
        "avg_12h_precision_30_delta_gte_10pp": float(vs_dev["headline"]["avg_12h_precision_30_delta"]) >= 0.10,
    }


def _profile_is_viable(
    summary: dict[str, Any],
    *,
    baseline_summary: dict[str, Any],
    vs_baseline: dict | None,
    vs_dev: dict | None,
) -> bool:
    checks = _profile_checks(
        summary,
        baseline_summary=baseline_summary,
        vs_baseline=vs_baseline,
        vs_dev=vs_dev,
    )
    return all(checks.values())


def _profile_sort_key(
    summary: dict[str, Any],
    *,
    baseline_summary: dict[str, Any],
    vs_baseline: dict | None,
    vs_dev: dict | None,
) -> tuple[float, float, float, float]:
    if not vs_baseline or not vs_dev:
        return (-1.0, -1.0, -1.0, -1.0)
    return (
        _eth4h_precision_30(summary),
        -_eth4h_validation_ece(summary),
        -_flat_class_ece(summary),
        float(vs_dev["headline"]["avg_12h_precision_30_delta"]),
    )


def _profile_result(
    summary: dict[str, Any],
    *,
    baseline_summary: dict[str, Any],
    baseline_name: str,
    vs_baseline: dict | None,
    vs_dev: dict,
) -> dict[str, Any]:
    payload = _eth4h_payload(summary)
    return {
        "eth4h_headline": bench.build_eth4h_headline(summary),
        "vs_codex_dev": vs_dev,
        "vs_baseline_long_history": vs_baseline,
        "checks": _profile_checks(
            summary,
            baseline_summary=baseline_summary,
            vs_baseline=vs_baseline,
            vs_dev=vs_dev,
        ),
        "baseline_profile": baseline_name,
        "baseline_threshold": _eth4h_payload(baseline_summary).get("label_threshold_pct"),
        "baseline_calibration_mode": _eth4h_payload(baseline_summary).get("probability_calibration_mode", "dirichlet"),
        "eth4h_flat_class_ece": float(payload.get("validation_classwise_ece", {}).get("flat", 0.0)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Focused ETH 4h signal-quality benchmark on top of the current QI pipeline.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--baseline-json", type=Path, required=True)
    parser.add_argument("--shared-cache-root", type=Path, required=True)
    parser.add_argument(
        "--threshold-values",
        "--history-values",
        dest="threshold_values",
        type=float,
        nargs="*",
        default=DEFAULT_THRESHOLD_CANDIDATES,
    )
    parser.add_argument("--reuse-baseline-artifact-root", type=Path, default=None)
    args = parser.parse_args()

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    baseline_summary = json.loads(args.baseline_json.read_text())
    shared_cache_root = args.shared_cache_root
    bench.prepare_history_bundle(
        shared_cache_root,
        settings=_settings_for(output_dir / BASELINE_PROFILE, threshold=0.0025, calibration_mode="dirichlet"),
    )

    current_profiles: dict[str, dict[str, Any]] = {}
    current_profiles[BASELINE_PROFILE] = bench.run_current_benchmark(
        output_dir,
        profile=BASELINE_PROFILE,
        settings=_settings_for(
            output_dir / BASELINE_PROFILE,
            threshold=0.0025,
            calibration_mode="dirichlet",
        ),
        shared_cache_root=shared_cache_root,
    )
    baseline_long_history = current_profiles[BASELINE_PROFILE]

    profile_specs = [
        ("eth4h_threshold_0p00275_dirichlet", 0.00275, "dirichlet"),
        ("eth4h_threshold_0p00275_flat_isotonic_rescale", 0.00275, "flat_isotonic_rescale"),
        ("eth4h_threshold_0p003_flat_isotonic_rescale", 0.0030, "flat_isotonic_rescale"),
    ]
    for profile_name, threshold, calibration_mode in profile_specs:
        current_profiles[profile_name] = bench.run_current_benchmark(
            output_dir,
            profile=profile_name,
            settings=_settings_for(
                output_dir / profile_name,
                threshold=threshold,
                calibration_mode=calibration_mode,
            ),
            shared_cache_root=shared_cache_root,
        )

    deltas_vs_dev = {name: bench.build_delta_report(summary, baseline_summary) for name, summary in current_profiles.items()}
    deltas_vs_baseline = {
        name: bench.build_delta_report(summary, baseline_long_history)
        for name, summary in current_profiles.items()
        if name != BASELINE_PROFILE
    }

    viable_profiles = [
        name
        for name in current_profiles
        if name != BASELINE_PROFILE
        and _profile_is_viable(
            current_profiles[name],
            baseline_summary=baseline_long_history,
            vs_baseline=deltas_vs_baseline.get(name),
            vs_dev=deltas_vs_dev.get(name),
        )
    ]
    selected_profile = (
        max(
            viable_profiles,
            key=lambda name: _profile_sort_key(
                current_profiles[name],
                baseline_summary=baseline_long_history,
                vs_baseline=deltas_vs_baseline.get(name),
                vs_dev=deltas_vs_dev.get(name),
            ),
        )
        if viable_profiles
        else BASELINE_PROFILE
    )

    result = {
        "baseline_profile": BASELINE_PROFILE,
        "baseline_threshold": _eth4h_payload(baseline_long_history).get("label_threshold_pct"),
        "baseline_calibration_mode": _eth4h_payload(baseline_long_history).get("probability_calibration_mode", "dirichlet"),
        "selected_profile": selected_profile,
        "profiles": {
            name: _profile_result(
                summary,
                baseline_summary=baseline_long_history,
                baseline_name=BASELINE_PROFILE,
                vs_baseline=None if name == BASELINE_PROFILE else deltas_vs_baseline.get(name),
                vs_dev=deltas_vs_dev[name],
            )
            for name, summary in current_profiles.items()
        },
    }
    report_path = output_dir / "eth4h_focused_report.json"
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({"report": str(report_path), "selected_profile": selected_profile}, ensure_ascii=False))


if __name__ == "__main__":
    main()
