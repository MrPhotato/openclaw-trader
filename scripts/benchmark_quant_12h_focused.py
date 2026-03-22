from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
from typing import Any

import benchmark_quant_intelligence as bench


BASELINE_PROFILE = "baseline_long_history"
THRESHOLD_CANDIDATES = (0.0025, 0.0030, 0.0035, 0.0040)


def _settings_for(
    runtime_root: Path,
    *,
    eth_threshold: float,
    sol_threshold: float,
    specialist_coin_horizons: list[str] | None = None,
    probability_calibration_mode_by_coin_horizon: dict[str, str] | None = None,
) -> Any:
    overrides = {
        "ETH:4h": 0.0025,
        "ETH:12h": float(eth_threshold),
        "SOL:12h": float(sol_threshold),
    }
    return bench.build_benchmark_settings(
        runtime_root,
        target_move_threshold_pct_overrides_by_coin_horizon=overrides,
        specialist_coin_horizons=specialist_coin_horizons or [],
        probability_calibration_mode_by_coin_horizon=probability_calibration_mode_by_coin_horizon or {},
    )


def _delta(summary: dict[str, Any], baseline: dict[str, Any], *, coin: str, horizon: str) -> float:
    return float(
        bench.build_delta_report(summary, baseline)["by_coin"][coin][horizon]["delta_precision_30"]
    )


def _headline(summary: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    delta = bench.build_delta_report(summary, baseline)
    return {
        "avg_12h_precision_30_delta": float(delta["headline"]["avg_12h_precision_30_delta"]),
        "avg_4h_precision_30_delta": float(delta["headline"]["avg_4h_precision_30_delta"]),
        "ece_improvement_ratio": float(delta["headline"]["ece_improvement_ratio"]),
        "eth_12h_delta": float(delta["by_coin"]["ETH"]["12h"]["delta_precision_30"]),
        "sol_12h_delta": float(delta["by_coin"]["SOL"]["12h"]["delta_precision_30"]),
    }


def _profile_checks(summary: dict[str, Any], *, baseline_summary: dict[str, Any], dev_summary: dict[str, Any]) -> dict[str, bool]:
    vs_dev = bench.build_delta_report(summary, dev_summary)
    vs_baseline = bench.build_delta_report(summary, baseline_summary)
    return {
        "avg_12h_precision_30_delta_gte_3pp": float(vs_dev["headline"]["avg_12h_precision_30_delta"]) >= 0.03,
        "eth_12h_not_negative": float(vs_dev["by_coin"]["ETH"]["12h"]["delta_precision_30"]) >= 0.0,
        "sol_12h_not_negative": float(vs_dev["by_coin"]["SOL"]["12h"]["delta_precision_30"]) >= 0.0,
        "avg_4h_not_worse_than_minus_1pp_vs_baseline": float(vs_baseline["headline"]["avg_4h_precision_30_delta"]) >= -0.01,
        "ece_improvement_gte_85pct": float(vs_dev["headline"]["ece_improvement_ratio"]) >= 0.85,
    }


def _profile_is_viable(summary: dict[str, Any], *, baseline_summary: dict[str, Any], dev_summary: dict[str, Any]) -> bool:
    return all(_profile_checks(summary, baseline_summary=baseline_summary, dev_summary=dev_summary).values())


def _profile_sort_key(summary: dict[str, Any], *, baseline_summary: dict[str, Any], dev_summary: dict[str, Any]) -> tuple[float, float, float, float]:
    vs_dev = bench.build_delta_report(summary, dev_summary)
    return (
        float(vs_dev["headline"]["avg_12h_precision_30_delta"]),
        min(
            float(vs_dev["by_coin"]["ETH"]["12h"]["delta_precision_30"]),
            float(vs_dev["by_coin"]["SOL"]["12h"]["delta_precision_30"]),
        ),
        float(vs_dev["headline"]["avg_4h_precision_30_delta"]),
        float(vs_dev["headline"]["ece_improvement_ratio"]),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Focused 12h benchmark with frozen data window.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--shared-cache-root", type=Path, required=True)
    parser.add_argument("--baseline-json", type=Path, default=None)
    args = parser.parse_args()

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    shared_cache_root = args.shared_cache_root

    baseline_settings = _settings_for(
        output_dir / BASELINE_PROFILE,
        eth_threshold=0.0025,
        sol_threshold=0.0025,
    )
    bench.prepare_history_bundle(shared_cache_root, settings=baseline_settings)

    baseline_current = bench.run_current_benchmark(
        output_dir,
        profile=BASELINE_PROFILE,
        settings=baseline_settings,
        shared_cache_root=shared_cache_root,
    )
    if args.baseline_json is not None:
        baseline_dev = json.loads(args.baseline_json.read_text())
    else:
        baseline_dev = bench.run_codex_dev_benchmark(
            output_dir,
            manifest_file=bench.history_manifest_path(shared_cache_root),
        )

    current_profiles: dict[str, dict[str, Any]] = {BASELINE_PROFILE: baseline_current}
    for eth_threshold, sol_threshold in itertools.product(THRESHOLD_CANDIDATES, repeat=2):
        profile = f"th12_eth_{str(eth_threshold).replace('.', 'p')}_sol_{str(sol_threshold).replace('.', 'p')}"
        current_profiles[profile] = bench.run_current_benchmark(
            output_dir,
            profile=profile,
            settings=_settings_for(
                output_dir / profile,
                eth_threshold=eth_threshold,
                sol_threshold=sol_threshold,
            ),
            shared_cache_root=shared_cache_root,
        )

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

    selected_summary = current_profiles[selected_profile]
    selected_vs_dev = bench.build_delta_report(selected_summary, baseline_dev)
    if selected_profile == BASELINE_PROFILE or (
        float(selected_vs_dev["by_coin"]["ETH"]["12h"]["delta_precision_30"]) < 0.0
        or float(selected_vs_dev["by_coin"]["SOL"]["12h"]["delta_precision_30"]) < 0.0
    ):
        specialist_profile = "th12_specialist_eth_sol"
        current_profiles[specialist_profile] = bench.run_current_benchmark(
            output_dir,
            profile=specialist_profile,
            settings=_settings_for(
                output_dir / specialist_profile,
                eth_threshold=float(selected_summary["coins"]["ETH"]["12h"].get("label_threshold_pct", 0.0025)),
                sol_threshold=float(selected_summary["coins"]["SOL"]["12h"].get("label_threshold_pct", 0.0025)),
                specialist_coin_horizons=["ETH:12h", "SOL:12h"],
            ),
            shared_cache_root=shared_cache_root,
        )
        if _profile_is_viable(current_profiles[specialist_profile], baseline_summary=baseline_current, dev_summary=baseline_dev):
            selected_profile = specialist_profile

    report = {
        "baseline_profile": BASELINE_PROFILE,
        "selected_profile": selected_profile,
        "history_bundle_manifest": json.loads(bench.history_manifest_path(shared_cache_root).read_text()),
        "profiles": {
            name: {
                "headline_vs_codex_dev": _headline(summary, baseline_dev),
                "headline_vs_baseline": _headline(summary, baseline_current),
                "checks": _profile_checks(summary, baseline_summary=baseline_current, dev_summary=baseline_dev),
                "eth12_threshold": summary["coins"]["ETH"]["12h"].get("label_threshold_pct"),
                "sol12_threshold": summary["coins"]["SOL"]["12h"].get("label_threshold_pct"),
                "eth12_specialist": summary["coins"]["ETH"]["12h"].get("specialist_summary", {}),
                "sol12_specialist": summary["coins"]["SOL"]["12h"].get("specialist_summary", {}),
            }
            for name, summary in current_profiles.items()
        },
    }
    report_path = output_dir / "th12_focused_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"report": str(report_path), "selected_profile": selected_profile}, ensure_ascii=False))


if __name__ == "__main__":
    main()
