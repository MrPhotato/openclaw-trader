from __future__ import annotations

from typing import Any

import numpy as np

from ....config.models import QuantSettings


def default_execution_policy(quant: QuantSettings) -> dict[str, float]:
    return {
        "min_confidence": round(float(quant.min_confidence), 4),
        "min_long_short_probability": round(float(quant.min_long_short_probability), 4),
        "meta_min_confidence": round(float(quant.meta_min_confidence), 4),
        "order_size_floor_ratio": round(float(quant.order_size_floor_ratio), 4),
        "order_size_ceiling_ratio": round(float(quant.order_size_ceiling_ratio), 4),
    }


def map_regime_labels(regime_state_ids: np.ndarray, state_map: dict[str, str]) -> np.ndarray:
    if len(regime_state_ids) == 0:
        return np.asarray([], dtype=object)
    labels: list[str] = []
    for state_id in regime_state_ids:
        if np.isfinite(state_id):
            labels.append(state_map.get(str(int(state_id)), "neutral_consolidation"))
        else:
            labels.append("neutral_consolidation")
    return np.asarray(labels, dtype=object)


def resolve_execution_policy(
    quant: QuantSettings,
    policy_bundle: dict[str, Any] | None,
    regime_label: str,
) -> dict[str, float]:
    defaults = default_execution_policy(quant)
    if not policy_bundle:
        return defaults
    global_policy = dict(defaults)
    global_policy.update(policy_bundle.get("global", {}))
    regime_entry = (policy_bundle.get("regimes") or {}).get(regime_label)
    if isinstance(regime_entry, dict):
        regime_policy = regime_entry.get("policy", regime_entry)
        merged = dict(global_policy)
        merged.update({key: float(value) for key, value in regime_policy.items() if key in defaults})
        return merged
    return global_policy


def _candidate_values(center: float, *, lower: float, upper: float, step: float) -> list[float]:
    values = {
        round(max(lower, min(upper, center - step)), 4),
        round(max(lower, min(upper, center)), 4),
        round(max(lower, min(upper, center + step)), 4),
    }
    return sorted(values)


def _policy_trade_outcomes(
    *,
    quant: QuantSettings,
    probabilities: np.ndarray,
    trade_quality: np.ndarray,
    net_long_returns: np.ndarray,
    net_short_returns: np.ndarray,
    regime_labels: np.ndarray,
    policy: dict[str, Any],
) -> dict[str, float]:
    trade_returns = np.zeros(len(probabilities), dtype=np.float64)
    trade_count = 0
    win_count = 0
    for idx in range(len(probabilities)):
        regime_label = str(regime_labels[idx]) if len(regime_labels) else "neutral_consolidation"
        regime_policy = resolve_execution_policy(quant, policy, regime_label)
        probability = probabilities[idx]
        class_index = int(np.argmax(probability))
        if class_index == 1:
            continue
        top_probability = float(np.max(probability))
        directional_probability = max(float(probability[0]), float(probability[2]))
        meta_probability = float(trade_quality[idx])
        combined_confidence = max(0.0, min((top_probability * 0.65) + (meta_probability * 0.35), 1.0))
        if top_probability < regime_policy["min_confidence"]:
            continue
        if directional_probability < regime_policy["min_long_short_probability"]:
            continue
        if meta_probability < regime_policy["meta_min_confidence"]:
            continue
        span = max(1e-6, 1.0 - regime_policy["min_confidence"])
        normalized = max(0.0, min((combined_confidence - regime_policy["min_confidence"]) / span, 1.0))
        size_ratio = regime_policy["order_size_floor_ratio"] + (
            (regime_policy["order_size_ceiling_ratio"] - regime_policy["order_size_floor_ratio"]) * normalized
        )
        size_ratio *= 0.5 + (0.5 * meta_probability)
        if regime_label == "neutral_consolidation":
            size_ratio *= quant.neutral_regime_size_scale
        if (regime_label == "bullish_trend" and class_index == 0) or (
            regime_label == "bearish_breakdown" and class_index == 2
        ):
            size_ratio *= quant.counter_regime_size_scale
        base_return = net_short_returns[idx] if class_index == 0 else net_long_returns[idx]
        realized = float(base_return) * float(size_ratio)
        trade_returns[idx] = realized
        trade_count += 1
        if realized > 0:
            win_count += 1
    executed = trade_returns[trade_returns != 0]
    trade_coverage = float(trade_count / max(len(probabilities), 1))
    trade_precision = float(win_count / trade_count) if trade_count else 0.0
    avg_net_return = float(np.mean(executed)) if len(executed) else 0.0
    total_net_return = float(np.sum(executed)) if len(executed) else 0.0
    downside = float(abs(np.sum(executed[executed < 0]))) if len(executed) else 0.0
    min_trades = max(4, int(len(probabilities) * 0.03))
    undertrade_penalty = max(0, min_trades - trade_count) * 0.0015
    precision_penalty = max(0.0, 0.45 - trade_precision) * 0.02
    objective = total_net_return - undertrade_penalty - precision_penalty - (downside * 0.15)
    return {
        "trade_precision": round(trade_precision, 4),
        "trade_coverage": round(trade_coverage, 4),
        "avg_net_return": round(avg_net_return, 6),
        "total_net_return": round(total_net_return, 6),
        "objective": round(objective, 6),
        "trade_count": trade_count,
    }


def _calibrate_regime_policy(
    *,
    quant: QuantSettings,
    base_policy: dict[str, float],
    probabilities: np.ndarray,
    trade_quality: np.ndarray,
    net_long_returns: np.ndarray,
    net_short_returns: np.ndarray,
    regime_labels: np.ndarray,
    regime_label: str | None = None,
) -> dict[str, Any]:
    current_policy = default_execution_policy(quant)
    min_conf_values = _candidate_values(
        base_policy["min_confidence"] if regime_label else current_policy["min_confidence"],
        lower=0.36,
        upper=0.68,
        step=0.04 if regime_label else 0.06,
    )
    min_dir_values = _candidate_values(
        base_policy["min_long_short_probability"] if regime_label else current_policy["min_long_short_probability"],
        lower=0.34,
        upper=0.68,
        step=0.04 if regime_label else 0.06,
    )
    meta_values = _candidate_values(
        base_policy["meta_min_confidence"] if regime_label else current_policy["meta_min_confidence"],
        lower=0.35,
        upper=0.75,
        step=0.05 if regime_label else 0.07,
    )
    floor_values = _candidate_values(
        base_policy["order_size_floor_ratio"] if regime_label else current_policy["order_size_floor_ratio"],
        lower=0.15,
        upper=0.75,
        step=0.08 if regime_label else 0.12,
    )
    ceiling_values = sorted(
        {
            round(max(0.45, min(1.0, value)), 4)
            for value in _candidate_values(
                base_policy["order_size_ceiling_ratio"] if regime_label else current_policy["order_size_ceiling_ratio"],
                lower=0.45,
                upper=1.0,
                step=0.1 if regime_label else 0.15,
            )
        }
    )
    candidate_policy = dict(base_policy)
    best_result = _policy_trade_outcomes(
        quant=quant,
        probabilities=probabilities,
        trade_quality=trade_quality,
        net_long_returns=net_long_returns,
        net_short_returns=net_short_returns,
        regime_labels=regime_labels,
        policy=({"global": candidate_policy, "regimes": {regime_label: candidate_policy}} if regime_label else {"global": candidate_policy, "regimes": {}}),
    )
    best_policy = dict(candidate_policy)
    for min_confidence in min_conf_values:
        for min_directional in min_dir_values:
            for meta_min in meta_values:
                for size_floor in floor_values:
                    for size_ceiling in ceiling_values:
                        if size_floor >= size_ceiling:
                            continue
                        tested = {
                            "min_confidence": min_confidence,
                            "min_long_short_probability": min_directional,
                            "meta_min_confidence": meta_min,
                            "order_size_floor_ratio": size_floor,
                            "order_size_ceiling_ratio": size_ceiling,
                        }
                        policy_bundle = (
                            {"global": base_policy, "regimes": {regime_label: tested}}
                            if regime_label
                            else {"global": tested, "regimes": {}}
                        )
                        result = _policy_trade_outcomes(
                            quant=quant,
                            probabilities=probabilities,
                            trade_quality=trade_quality,
                            net_long_returns=net_long_returns,
                            net_short_returns=net_short_returns,
                            regime_labels=regime_labels,
                            policy=policy_bundle,
                        )
                        if result["objective"] > best_result["objective"]:
                            best_policy = tested
                            best_result = result
    return {
        "policy": {key: round(float(value), 4) for key, value in best_policy.items()},
        "metrics": best_result,
    }


def calibrate_execution_policy(
    *,
    quant: QuantSettings,
    probabilities: np.ndarray,
    trade_quality: np.ndarray,
    net_long_returns: np.ndarray,
    net_short_returns: np.ndarray,
    regime_labels: np.ndarray,
) -> dict[str, Any]:
    base_policy = default_execution_policy(quant)
    global_result = _calibrate_regime_policy(
        quant=quant,
        base_policy=base_policy,
        probabilities=probabilities,
        trade_quality=trade_quality,
        net_long_returns=net_long_returns,
        net_short_returns=net_short_returns,
        regime_labels=regime_labels,
    )
    overrides: dict[str, dict[str, Any]] = {}
    for label in ("bullish_trend", "bearish_breakdown", "neutral_consolidation"):
        mask = regime_labels == label
        if int(np.sum(mask)) < 60:
            continue
        result = _calibrate_regime_policy(
            quant=quant,
            base_policy=global_result["policy"],
            probabilities=probabilities[mask],
            trade_quality=trade_quality[mask],
            net_long_returns=net_long_returns[mask],
            net_short_returns=net_short_returns[mask],
            regime_labels=regime_labels[mask],
            regime_label=label,
        )
        overrides[label] = result
    return {
        "global": global_result["policy"],
        "global_metrics": global_result["metrics"],
        "regimes": overrides,
        "source": "walk_forward_calibration",
    }


def _policy_delta(default_policy: dict[str, float], current_policy: dict[str, Any]) -> dict[str, float]:
    return {
        key: round(float(current_policy.get(key, default_policy[key])) - float(default_policy[key]), 4)
        for key in default_policy
    }


def build_calibration_report_payload(meta: dict[str, Any], *, quant: QuantSettings) -> dict[str, Any]:
    base_policy = default_execution_policy(quant)
    calibrated = meta.get("calibrated_policy") or {}
    global_policy = calibrated.get("global", base_policy)
    report: dict[str, Any] = {
        "coin": meta["coin"],
        "horizon": meta.get("horizon"),
        "trained_at": meta["trained_at"],
        "artifact_version": meta["artifact_version"],
        "training_scope": meta.get("training_scope", "single_coin"),
        "panel_coins": meta.get("panel_coins", []),
        "training_rows": meta["training_rows"],
        "panel_training_rows": meta.get("panel_training_rows"),
        "coin_training_rows": meta.get("coin_training_rows"),
        "validation_accuracy": meta["validation_accuracy"],
        "validation_macro_f1": meta["validation_macro_f1"],
        "validation_brier": meta.get("validation_brier"),
        "validation_log_loss": meta.get("validation_log_loss"),
        "validation_ece": meta.get("validation_ece"),
        "validation_classwise_ece": meta.get("validation_classwise_ece", {}),
        "probability_calibration_mode": meta.get("probability_calibration_mode", "dirichlet"),
        "classwise_ece_before_post_calibration": meta.get("classwise_ece_before_post_calibration", {}),
        "classwise_ece_after_post_calibration": meta.get("classwise_ece_after_post_calibration", {}),
        "flat_class_post_calibration_metrics": meta.get("flat_class_post_calibration_metrics", {}),
        "walk_forward": meta.get("walk_forward", {}),
        "acceptance_policy": meta.get("acceptance_policy", {}),
        "acceptance_score_mode": meta.get("acceptance_score_mode"),
        "acceptance_score_weights": meta.get("acceptance_score_weights", {}),
        "acceptance_score_metrics": meta.get("acceptance_score_metrics", {}),
        "regime_acceptance_policy": meta.get("regime_acceptance_policy", {}),
        "high_confidence_metrics": meta.get("high_confidence_metrics", {}),
        "regime_metrics": meta.get("regime_metrics", {}),
        "snapshot_quality": meta.get("snapshot_quality", {}),
        "feature_family_summary": {
            "reference": len(meta.get("reference_features", [])),
            "time_context": len(meta.get("time_context_features", [])),
            "snapshot": len(meta.get("market_snapshot_features", [])),
            "interaction": len(meta.get("interaction_features", [])),
            "total": len(meta.get("feature_names", [])),
        },
        "default_policy": base_policy,
        "global_policy": global_policy,
        "global_policy_delta": _policy_delta(base_policy, global_policy),
        "global_metrics": calibrated.get("global_metrics", {}),
        "regimes": {},
    }
    for regime_label, payload in (calibrated.get("regimes") or {}).items():
        policy = payload.get("policy", payload)
        report["regimes"][regime_label] = {
            "policy": policy,
            "policy_delta_vs_default": _policy_delta(base_policy, policy),
            "metrics": payload.get("metrics", {}),
        }
    return report


def _render_policy_lines(policy: dict[str, Any], delta: dict[str, Any] | None = None) -> list[str]:
    lines: list[str] = []
    for key in (
        "min_confidence",
        "min_long_short_probability",
        "meta_min_confidence",
        "order_size_floor_ratio",
        "order_size_ceiling_ratio",
    ):
        value = policy.get(key)
        if delta and key in delta:
            change = float(delta[key])
            lines.append(f"- `{key}`: `{value}` ({change:+.4f})")
        else:
            lines.append(f"- `{key}`: `{value}`")
    return lines


def render_calibration_report_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# {report['coin']} Perp Model Calibration Report",
        "",
        f"- Horizon: `{report.get('horizon')}`",
        f"- Trained at: `{report['trained_at']}`",
        f"- Training scope: `{report.get('training_scope')}`",
        f"- Training rows: `{report['training_rows']}`",
        f"- Panel training rows: `{report.get('panel_training_rows')}`",
        f"- Coin training rows: `{report.get('coin_training_rows')}`",
        f"- Validation accuracy: `{report['validation_accuracy']}`",
        f"- Validation macro F1: `{report['validation_macro_f1']}`",
        f"- Validation Brier: `{report.get('validation_brier')}`",
        f"- Validation log loss: `{report.get('validation_log_loss')}`",
        f"- Validation ECE: `{report.get('validation_ece')}`",
        f"- Probability calibration mode: `{report.get('probability_calibration_mode')}`",
    ]
    if report.get("panel_coins"):
        lines.append(f"- Panel coins: `{', '.join(report['panel_coins'])}`")
    lines.extend(["", "## Walk-Forward Summary", ""])
    for key in (
        "rows",
        "folds",
        "embargo_bars",
        "time_blocks",
        "avg_lgbm_weight",
        "blended_accuracy",
        "blended_macro_f1",
        "blended_trade_precision",
        "blended_trade_coverage",
        "blended_avg_net_return",
        "blended_brier",
        "blended_log_loss",
        "blended_ece",
    ):
        value = report.get("walk_forward", {}).get(key)
        lines.append(f"- `{key}`: `{value}`")
    feature_summary = report.get("feature_family_summary") or {}
    if feature_summary:
        lines.extend(
            [
                "",
                "## Feature Families",
                "",
                f"- `total`: `{feature_summary.get('total')}`",
                f"- `reference`: `{feature_summary.get('reference')}`",
                f"- `time_context`: `{feature_summary.get('time_context')}`",
                f"- `snapshot`: `{feature_summary.get('snapshot')}`",
                f"- `interaction`: `{feature_summary.get('interaction')}`",
            ]
        )
    acceptance = report.get("acceptance_policy") or {}
    if acceptance:
        lines.extend(["", "## High-Confidence Acceptance", ""])
        lines.append(f"- `mode`: `{acceptance.get('mode', report.get('acceptance_score_mode'))}`")
        lines.append(f"- `target_coverage`: `{acceptance.get('target_coverage')}`")
        lines.append(f"- `achieved_coverage`: `{acceptance.get('achieved_coverage')}`")
        lines.append(f"- `achieved_precision`: `{acceptance.get('achieved_precision')}`")
        if str(acceptance.get("mode", "")).strip() == "score_rank":
            lines.append(f"- `min_score`: `{acceptance.get('min_score')}`")
            lines.append(f"- `components`: `{acceptance.get('components')}`")
            if report.get("acceptance_score_weights"):
                lines.append(f"- `weights`: `{report.get('acceptance_score_weights')}`")
            regime_acceptance = report.get("regime_acceptance_policy") or {}
            if regime_acceptance:
                lines.append(f"- `regime_acceptance_active`: `{regime_acceptance.get('active')}`")
                if regime_acceptance.get("coverage_caps"):
                    lines.append(f"- `regime_coverage_caps`: `{regime_acceptance.get('coverage_caps')}`")
                if regime_acceptance.get("regime_min_scores"):
                    lines.append(f"- `regime_min_scores`: `{regime_acceptance.get('regime_min_scores')}`")
        else:
            lines.append(f"- `min_top_probability`: `{acceptance.get('min_top_probability')}`")
            lines.append(f"- `min_margin`: `{acceptance.get('min_margin')}`")
            lines.append(f"- `max_entropy`: `{acceptance.get('max_entropy')}`")
    acceptance_score_metrics = report.get("acceptance_score_metrics") or {}
    if acceptance_score_metrics:
        lines.extend(["", "### Acceptance Score Metrics", ""])
        for key, value in acceptance_score_metrics.items():
            lines.append(f"- `{key}`: `{value}`")
    high_confidence = report.get("high_confidence_metrics") or {}
    precision_table = high_confidence.get("precision_at_coverage") or {}
    if precision_table:
        lines.extend(["", "## Precision At Coverage", ""])
        for coverage_label, payload in precision_table.items():
            lines.append(
                f"- `{coverage_label}`: precision=`{payload.get('precision')}`, coverage=`{payload.get('achieved_coverage')}`, trade_precision=`{payload.get('trade_precision')}`, avg_net_return=`{payload.get('avg_net_return')}`"
            )
    flat_post = report.get("flat_class_post_calibration_metrics") or {}
    if flat_post:
        lines.extend(["", "## Flat Class Post Calibration", ""])
        for key, value in flat_post.items():
            lines.append(f"- `{key}`: `{value}`")
    target_policy = high_confidence.get("target_policy") or {}
    if target_policy:
        lines.extend(
            [
                "",
                "### Target Policy Slice",
                "",
                f"- `target_coverage`: `{target_policy.get('target_coverage')}`",
                f"- `achieved_coverage`: `{target_policy.get('achieved_coverage')}`",
                f"- `precision`: `{target_policy.get('precision')}`",
                f"- `trade_precision`: `{target_policy.get('trade_precision')}`",
                f"- `avg_net_return`: `{target_policy.get('avg_net_return')}`",
                f"- `avg_score`: `{target_policy.get('avg_score')}`",
            ]
        )
    regime_metrics = report.get("regime_metrics") or {}
    regime_table = regime_metrics.get("by_regime") or {}
    if regime_table:
        lines.extend(
            [
                "",
                "## Regime Split",
                "",
                f"- `precision_std`: `{regime_metrics.get('precision_std')}`",
                f"- `precision_range`: `{regime_metrics.get('precision_range')}`",
            ]
        )
        for regime_label, payload in regime_table.items():
            lines.append(
                f"- `{regime_label}`: rows=`{payload.get('rows')}`, coverage=`{payload.get('coverage')}`, precision=`{payload.get('precision')}`, trade_precision=`{payload.get('trade_precision')}`, avg_net_return=`{payload.get('avg_net_return')}`"
            )
    snapshot_quality = report.get("snapshot_quality") or {}
    if snapshot_quality:
        lines.extend(
            [
                "",
                "## Snapshot Feature Quality",
                "",
                f"- `snapshot_avg_coverage`: `{snapshot_quality.get('snapshot_avg_coverage')}`",
                f"- `snapshot_rejected_rows`: `{snapshot_quality.get('snapshot_rejected_rows')}`",
                f"- `snapshot_downweighted_rows`: `{snapshot_quality.get('snapshot_downweighted_rows')}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Default Policy",
            "",
            *_render_policy_lines(report["default_policy"]),
            "",
            "## Calibrated Global Policy",
            "",
            *_render_policy_lines(report["global_policy"], report.get("global_policy_delta")),
            "",
            "### Global Outcome",
            "",
        ]
    )
    for key, value in (report.get("global_metrics") or {}).items():
        lines.append(f"- `{key}`: `{value}`")
    regimes = report.get("regimes") or {}
    if regimes:
        lines.extend(["", "## Regime Overrides", ""])
        for regime_label, payload in regimes.items():
            lines.extend([f"### {regime_label}", ""])
            lines.extend(_render_policy_lines(payload.get("policy", {}), payload.get("policy_delta_vs_default")))
            metrics = payload.get("metrics") or {}
            if metrics:
                lines.extend(["", "Outcome:"])
                for key, value in metrics.items():
                    lines.append(f"- `{key}`: `{value}`")
            lines.append("")
    return "\n".join(lines).strip() + "\n"
