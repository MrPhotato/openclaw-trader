from __future__ import annotations

from itertools import product
from typing import Any
import warnings

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, log_loss


SIDE_LABELS = ("short", "flat", "long")


def latest_valid_index(valid_mask: np.ndarray) -> int | None:
    valid_indices = np.where(valid_mask)[0]
    if len(valid_indices) == 0:
        return None
    return int(valid_indices[-1])


def _normalize_probabilities(probabilities: np.ndarray) -> np.ndarray:
    probs = np.asarray(probabilities, dtype=np.float64)
    if probs.ndim == 1:
        probs = probs.reshape(1, -1)
    probs = np.clip(probs, 1e-9, 1.0)
    row_sums = probs.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1.0
    return probs / row_sums


def expand_probabilities(model: Any, raw_probabilities: np.ndarray) -> np.ndarray:
    expanded = np.zeros((len(raw_probabilities), 3), dtype=np.float64)
    classes = getattr(model, "classes_", np.asarray([0, 1, 2], dtype=np.int32))
    for index, class_id in enumerate(classes):
        expanded[:, int(class_id)] = raw_probabilities[:, index]
    return _normalize_probabilities(expanded)


def predict_base_probabilities(
    models: dict[str, Any],
    x: np.ndarray,
    *,
    suppress_feature_name_warnings: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    constant_probs = models.get("constant_probs")
    if constant_probs is not None:
        tiled = np.tile(np.asarray(constant_probs, dtype=np.float64), (len(x), 1))
        tiled = _normalize_probabilities(tiled)
        return tiled, tiled
    with warnings.catch_warnings():
        if suppress_feature_name_warnings:
            warnings.filterwarnings("ignore", message="X does not have valid feature names")
        lgbm_raw = models["lgbm"].predict_proba(x)
        linear_raw = models["linear"].predict_proba(models["linear_scaler"].transform(x))
    return (
        expand_probabilities(models["lgbm"], np.asarray(lgbm_raw, dtype=np.float64)),
        expand_probabilities(models["linear"], np.asarray(linear_raw, dtype=np.float64)),
    )


def blend_probabilities(lgbm_probs: np.ndarray, linear_probs: np.ndarray, *, lgbm_weight: float) -> np.ndarray:
    weight = max(0.05, min(float(lgbm_weight), 0.95))
    blended = (weight * lgbm_probs) + ((1.0 - weight) * linear_probs)
    return _normalize_probabilities(blended)


def top_two_margin(probabilities: np.ndarray) -> np.ndarray:
    probs = _normalize_probabilities(probabilities)
    if len(probs) == 0:
        return np.empty((0,), dtype=np.float64)
    sorted_probs = np.sort(probs, axis=1)
    return sorted_probs[:, -1] - sorted_probs[:, -2]


def normalized_entropy(probabilities: np.ndarray) -> np.ndarray:
    probs = _normalize_probabilities(probabilities)
    if len(probs) == 0:
        return np.empty((0,), dtype=np.float64)
    entropy = -np.sum(probs * np.log(probs), axis=1)
    return entropy / np.log(probs.shape[1])


def _normalize_score_weights(
    components: list[str],
    weights: dict[str, float] | None,
) -> dict[str, float]:
    if not components:
        return {}
    raw_weights = {
        component: max(float((weights or {}).get(component, 0.0)), 0.0)
        for component in components
    }
    total = float(sum(raw_weights.values()))
    if total <= 0:
        equal_weight = round(1.0 / len(components), 6)
        return {component: equal_weight for component in components}
    return {
        component: round(float(value) / total, 6)
        for component, value in raw_weights.items()
    }


def _acceptance_score_components(
    probabilities: np.ndarray,
    *,
    trade_quality: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    probs = _normalize_probabilities(probabilities)
    top_probability = np.max(probs, axis=1) if len(probs) else np.empty((0,), dtype=np.float64)
    margin = top_two_margin(probs)
    entropy = normalized_entropy(probs)
    quality = np.asarray(trade_quality, dtype=np.float64) if trade_quality is not None else np.ones(len(probs), dtype=np.float64)
    if len(quality) != len(probs):
        quality = np.ones(len(probs), dtype=np.float64)
    quality = np.clip(np.nan_to_num(quality, nan=1.0), 0.0, 1.0)
    return {
        "calibrated_top_probability": top_probability,
        "top_two_margin": margin,
        "inverse_normalized_entropy": 1.0 - entropy,
        "meta_trade_quality_probability": quality,
    }


def compute_acceptance_scores(
    probabilities: np.ndarray,
    *,
    trade_quality: np.ndarray | None = None,
    components: list[str] | None = None,
    weights: dict[str, float] | None = None,
) -> tuple[np.ndarray, dict[str, float]]:
    component_map = _acceptance_score_components(probabilities, trade_quality=trade_quality)
    selected_components = [
        str(component).strip()
        for component in list(components or [])
        if str(component).strip() in component_map
    ]
    if not selected_components:
        selected_components = ["calibrated_top_probability"]
    normalized_weights = _normalize_score_weights(selected_components, weights)
    scores = np.zeros(len(next(iter(component_map.values()), np.empty((0,), dtype=np.float64))), dtype=np.float64)
    for component in selected_components:
        scores += component_map[component] * float(normalized_weights.get(component, 0.0))
    return np.clip(scores, 0.0, 1.0), normalized_weights


def build_regime_capped_coverage_mask(
    ranking_scores: np.ndarray,
    coverage: float,
    *,
    regime_labels: np.ndarray,
    regime_coverage_caps: dict[str, float],
) -> np.ndarray:
    scores = np.asarray(ranking_scores, dtype=np.float64)
    if len(scores) == 0:
        return np.zeros((0,), dtype=bool)
    target = min(max(float(coverage), 0.01), 1.0)
    keep_count = min(len(scores), max(1, int(np.ceil(len(scores) * target))))
    order = np.argsort(-scores, kind="mergesort")
    labels = np.asarray(regime_labels, dtype=object)
    accepted = np.zeros(len(scores), dtype=bool)
    regime_counts: dict[str, int] = {}
    max_counts = {
        str(label): int(np.ceil(len(scores) * min(max(float(cap), 0.0), 1.0)))
        for label, cap in dict(regime_coverage_caps or {}).items()
    }
    selected = 0
    for idx in order:
        regime_label = str(labels[idx]) if len(labels) > idx else "neutral_consolidation"
        max_count = max_counts.get(regime_label)
        if max_count is not None and regime_counts.get(regime_label, 0) >= max_count:
            continue
        accepted[idx] = True
        regime_counts[regime_label] = regime_counts.get(regime_label, 0) + 1
        selected += 1
        if selected >= keep_count:
            break
    return accepted


def build_meta_features(probabilities: np.ndarray) -> np.ndarray:
    probs = _normalize_probabilities(probabilities)
    prob_short = probs[:, 0]
    prob_flat = probs[:, 1]
    prob_long = probs[:, 2]
    directional_prob = np.maximum(prob_short, prob_long)
    top_probability = np.max(probs, axis=1)
    flat_gap = directional_prob - prob_flat
    side_gap = np.abs(prob_long - prob_short)
    entropy = normalized_entropy(probs)
    margin = top_two_margin(probs)
    return np.column_stack(
        [prob_short, prob_flat, prob_long, directional_prob, top_probability, flat_gap, side_gap, entropy, margin]
    )


def build_meta_labels(probabilities: np.ndarray, net_long_returns: np.ndarray, net_short_returns: np.ndarray) -> np.ndarray:
    prediction = np.argmax(_normalize_probabilities(probabilities), axis=1)
    labels = np.zeros(len(prediction), dtype=np.int32)
    labels[(prediction == 0) & (net_short_returns > 0)] = 1
    labels[(prediction == 2) & (net_long_returns > 0)] = 1
    return labels


def fit_meta_model(
    meta_x: np.ndarray,
    meta_y: np.ndarray,
    *,
    random_seed: int,
    sample_weight: np.ndarray | None = None,
) -> LogisticRegression | None:
    if len(meta_x) == 0 or len(np.unique(meta_y)) < 2:
        return None
    model = LogisticRegression(max_iter=300, class_weight="balanced", random_state=random_seed)
    fit_kwargs: dict[str, Any] = {}
    if sample_weight is not None and len(sample_weight) == len(meta_y):
        fit_kwargs["sample_weight"] = sample_weight
    model.fit(meta_x, meta_y, **fit_kwargs)
    return model


def fit_meta_calibrator(
    meta_model: LogisticRegression | None,
    meta_x: np.ndarray,
    meta_y: np.ndarray,
    *,
    sample_weight: np.ndarray | None = None,
) -> IsotonicRegression | None:
    if meta_model is None or len(meta_x) == 0 or len(np.unique(meta_y)) < 2:
        return None
    raw = meta_model.predict_proba(meta_x)[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip")
    fit_kwargs: dict[str, Any] = {}
    if sample_weight is not None and len(sample_weight) == len(meta_y):
        fit_kwargs["sample_weight"] = sample_weight
    calibrator.fit(raw, meta_y, **fit_kwargs)
    return calibrator


def fit_dirichlet_calibrator(
    probabilities: np.ndarray,
    y_true: np.ndarray,
    *,
    random_seed: int,
    sample_weight: np.ndarray | None = None,
) -> LogisticRegression | None:
    probs = _normalize_probabilities(probabilities)
    if len(probs) == 0 or len(np.unique(y_true)) < 2:
        return None
    model = LogisticRegression(
        max_iter=400,
        class_weight="balanced",
        random_state=random_seed,
    )
    x = np.log(probs)
    fit_kwargs: dict[str, Any] = {}
    if sample_weight is not None and len(sample_weight) == len(y_true):
        fit_kwargs["sample_weight"] = sample_weight
    model.fit(x, y_true, **fit_kwargs)
    return model


def fit_flat_isotonic_calibrator(
    probabilities: np.ndarray,
    y_true: np.ndarray,
    *,
    sample_weight: np.ndarray | None = None,
) -> IsotonicRegression | None:
    probs = _normalize_probabilities(probabilities)
    if len(probs) == 0:
        return None
    target = (np.asarray(y_true, dtype=np.int32) == 1).astype(np.float64)
    if len(np.unique(target)) < 2:
        return None
    calibrator = IsotonicRegression(out_of_bounds="clip")
    fit_kwargs: dict[str, Any] = {}
    if sample_weight is not None and len(sample_weight) == len(target):
        fit_kwargs["sample_weight"] = sample_weight
    calibrator.fit(probs[:, 1], target, **fit_kwargs)
    return calibrator


def apply_dirichlet_calibration(
    calibrator: LogisticRegression | None,
    probabilities: np.ndarray,
) -> np.ndarray:
    probs = _normalize_probabilities(probabilities)
    if calibrator is None or len(probs) == 0:
        return probs
    return _normalize_probabilities(calibrator.predict_proba(np.log(probs)))


def apply_flat_isotonic_rescale(
    calibrator: IsotonicRegression | None,
    probabilities: np.ndarray,
) -> np.ndarray:
    probs = _normalize_probabilities(probabilities)
    if calibrator is None or len(probs) == 0:
        return probs
    adjusted_flat = np.clip(np.asarray(calibrator.transform(probs[:, 1]), dtype=np.float64), 0.0, 1.0)
    side_mass = np.clip(probs[:, 0] + probs[:, 2], 0.0, 1.0)
    remaining_mass = np.clip(1.0 - adjusted_flat, 0.0, 1.0)
    scaled = probs.copy()
    nonzero_side_mass = side_mass > 1e-9
    scaled[nonzero_side_mass, 0] = remaining_mass[nonzero_side_mass] * (probs[nonzero_side_mass, 0] / side_mass[nonzero_side_mass])
    scaled[nonzero_side_mass, 2] = remaining_mass[nonzero_side_mass] * (probs[nonzero_side_mass, 2] / side_mass[nonzero_side_mass])
    scaled[~nonzero_side_mass, 0] = remaining_mass[~nonzero_side_mass] * 0.5
    scaled[~nonzero_side_mass, 2] = remaining_mass[~nonzero_side_mass] * 0.5
    scaled[:, 1] = adjusted_flat
    return _normalize_probabilities(scaled)


def summarize_flat_post_calibration(
    y_true: np.ndarray,
    before_probabilities: np.ndarray,
    after_probabilities: np.ndarray,
    *,
    active: bool,
) -> dict[str, Any]:
    before_probs = _normalize_probabilities(before_probabilities)
    after_probs = _normalize_probabilities(after_probabilities)
    flat_target = (np.asarray(y_true, dtype=np.int32) == 1).astype(np.float64)
    before_flat = before_probs[:, 1] if len(before_probs) else np.empty((0,), dtype=np.float64)
    after_flat = after_probs[:, 1] if len(after_probs) else np.empty((0,), dtype=np.float64)

    def _flat_ece(flat_probs: np.ndarray) -> float:
        if len(flat_probs) == 0:
            return 0.0
        edges = np.linspace(0.0, 1.0, 11)
        ece = 0.0
        for start, end in zip(edges[:-1], edges[1:]):
            if end >= 1.0:
                mask = (flat_probs >= start) & (flat_probs <= end)
            else:
                mask = (flat_probs >= start) & (flat_probs < end)
            if not np.any(mask):
                continue
            bin_conf = float(np.mean(flat_probs[mask]))
            bin_acc = float(np.mean(flat_target[mask]))
            ece += float(np.mean(mask)) * abs(bin_acc - bin_conf)
        return ece

    return {
        "active": bool(active),
        "before_flat_ece": round(_flat_ece(before_flat), 6),
        "after_flat_ece": round(_flat_ece(after_flat), 6),
        "avg_flat_probability_before": round(float(np.mean(before_flat)) if len(before_flat) else 0.0, 6),
        "avg_flat_probability_after": round(float(np.mean(after_flat)) if len(after_flat) else 0.0, 6),
        "mean_abs_flat_probability_delta": round(
            float(np.mean(np.abs(after_flat - before_flat))) if len(before_flat) else 0.0,
            6,
        ),
    }


def predict_meta_probability(
    meta_model: Any | None,
    meta_calibrator: Any | None,
    meta_x: np.ndarray,
) -> np.ndarray:
    if len(meta_x) == 0:
        return np.empty((0,), dtype=np.float64)
    if meta_model is None:
        return np.ones(len(meta_x), dtype=np.float64)
    raw = meta_model.predict_proba(meta_x)[:, 1]
    if meta_calibrator is None:
        return raw
    return np.asarray(meta_calibrator.transform(raw), dtype=np.float64)


def multiclass_brier_score(y_true: np.ndarray, probabilities: np.ndarray) -> float:
    probs = _normalize_probabilities(probabilities)
    if len(y_true) == 0:
        return 0.0
    target = np.zeros_like(probs)
    target[np.arange(len(y_true)), y_true.astype(int)] = 1.0
    return float(np.mean(np.sum((probs - target) ** 2, axis=1)))


def expected_calibration_error(
    y_true: np.ndarray,
    probabilities: np.ndarray,
    *,
    bins: int = 10,
) -> float:
    probs = _normalize_probabilities(probabilities)
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
        bin_conf = float(np.mean(confidence[mask]))
        bin_acc = float(np.mean(correctness[mask]))
        ece += float(np.mean(mask)) * abs(bin_acc - bin_conf)
    return float(ece)


def classwise_expected_calibration_error(
    y_true: np.ndarray,
    probabilities: np.ndarray,
    *,
    bins: int = 10,
) -> dict[str, float]:
    probs = _normalize_probabilities(probabilities)
    results: dict[str, float] = {}
    for class_idx, label in enumerate(SIDE_LABELS):
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
            bin_conf = float(np.mean(class_probs[mask]))
            bin_acc = float(np.mean(class_target[mask]))
            ece += float(np.mean(mask)) * abs(bin_acc - bin_conf)
        results[label] = round(float(ece), 6)
    return results


def prediction_metrics(
    y_true: np.ndarray,
    probabilities: np.ndarray,
    net_long_returns: np.ndarray,
    net_short_returns: np.ndarray,
    *,
    trade_quality: np.ndarray | None = None,
    sample_weight: np.ndarray | None = None,
) -> dict[str, float | dict[str, float]]:
    probs = _normalize_probabilities(probabilities)
    if len(y_true) == 0:
        return {
            "accuracy": 0.0,
            "macro_f1": 0.0,
            "trade_precision": 0.0,
            "trade_coverage": 0.0,
            "avg_net_return": 0.0,
            "brier": 0.0,
            "log_loss": 0.0,
            "ece": 0.0,
            "classwise_ece": {},
        }
    prediction = np.argmax(probs, axis=1)
    weight = sample_weight if sample_weight is not None and len(sample_weight) == len(y_true) else None
    accuracy = float(accuracy_score(y_true, prediction, sample_weight=weight))
    macro_f1 = float(f1_score(y_true, prediction, average="macro", zero_division=0, sample_weight=weight))
    trade_mask = prediction != 1
    realized_returns = np.zeros(len(prediction), dtype=np.float64)
    realized_returns[prediction == 0] = net_short_returns[prediction == 0]
    realized_returns[prediction == 2] = net_long_returns[prediction == 2]
    if trade_quality is not None:
        realized_returns = realized_returns * trade_quality
    trade_precision = float(np.mean(realized_returns[trade_mask] > 0)) if np.any(trade_mask) else 0.0
    trade_coverage = float(np.mean(trade_mask)) if len(trade_mask) else 0.0
    avg_net_return = float(np.mean(realized_returns[trade_mask])) if np.any(trade_mask) else 0.0
    return {
        "accuracy": round(accuracy, 4),
        "macro_f1": round(macro_f1, 4),
        "trade_precision": round(trade_precision, 4),
        "trade_coverage": round(trade_coverage, 4),
        "avg_net_return": round(avg_net_return, 6),
        "brier": round(multiclass_brier_score(y_true, probs), 6),
        "log_loss": round(float(log_loss(y_true, probs, labels=[0, 1, 2])), 6),
        "ece": round(expected_calibration_error(y_true, probs), 6),
        "classwise_ece": classwise_expected_calibration_error(y_true, probs),
    }


def resolve_blend_weight(metrics: dict[str, dict[str, float]]) -> float:
    lgbm_f1 = float(metrics.get("lgbm", {}).get("macro_f1", 0.0))
    linear_f1 = float(metrics.get("linear", {}).get("macro_f1", 0.0))
    total = lgbm_f1 + linear_f1
    if total <= 0:
        return 0.6
    return max(0.2, min(lgbm_f1 / total, 0.8))


def build_high_confidence_policy(
    probabilities: np.ndarray,
    y_true: np.ndarray,
    *,
    target_coverage: float,
    trade_quality: np.ndarray | None = None,
    regime_labels: np.ndarray | None = None,
    score_components: list[str] | None = None,
    score_weights: dict[str, float] | None = None,
    regime_coverage_caps: dict[str, float] | None = None,
) -> dict[str, Any]:
    probs = _normalize_probabilities(probabilities)
    if len(y_true) == 0:
        return {
            "mode": "threshold_filters",
            "min_top_probability": 1.0,
            "min_margin": 1.0,
            "max_entropy": 0.0,
            "target_coverage": round(float(target_coverage), 4),
            "achieved_coverage": 0.0,
            "achieved_precision": 0.0,
        }
    if score_components:
        ranking_scores, normalized_weights = compute_acceptance_scores(
            probs,
            trade_quality=trade_quality,
            components=score_components,
            weights=score_weights,
        )
        accepted = build_fixed_coverage_mask(
            probs,
            target_coverage,
            ranking_scores=ranking_scores,
            regime_labels=regime_labels,
            regime_coverage_caps=regime_coverage_caps,
        )
        prediction = np.argmax(probs, axis=1)
        precision = float(np.mean(prediction[accepted] == y_true[accepted])) if np.any(accepted) else 0.0
        min_score = float(np.min(ranking_scores[accepted])) if np.any(accepted) else 1.0
        regime_min_scores: dict[str, float] = {}
        if regime_labels is not None and np.any(accepted):
            labels = np.asarray(regime_labels, dtype=object)
            for label in sorted({str(item) for item in labels[accepted]}):
                regime_mask = accepted & (labels == label)
                if np.any(regime_mask):
                    regime_min_scores[label] = round(float(np.min(ranking_scores[regime_mask])), 6)
        return {
            "mode": "score_rank",
            "components": list(score_components),
            "weights": normalized_weights,
            "min_score": round(min_score, 6),
            "regime_min_scores": regime_min_scores,
            "regime_coverage_caps": {
                str(label): round(float(value), 6)
                for label, value in dict(regime_coverage_caps or {}).items()
            },
            "target_coverage": round(float(target_coverage), 4),
            "achieved_coverage": round(float(np.mean(accepted)), 4),
            "achieved_precision": round(precision, 4),
            "score_stats": {
                "min": round(float(np.min(ranking_scores)) if len(ranking_scores) else 0.0, 6),
                "median": round(float(np.median(ranking_scores)) if len(ranking_scores) else 0.0, 6),
                "max": round(float(np.max(ranking_scores)) if len(ranking_scores) else 0.0, 6),
            },
        }
    top_prob = np.max(probs, axis=1)
    margin = top_two_margin(probs)
    entropy = normalized_entropy(probs)
    predicted = np.argmax(probs, axis=1)
    lower_quantile = max(0.0, 1.0 - min(max(target_coverage * 1.6, 0.2), 0.95))
    top_candidates = np.unique(np.quantile(top_prob, [lower_quantile, 0.55, 0.65, 0.75, 0.85]))
    margin_candidates = np.unique(np.quantile(margin, [0.2, 0.35, 0.5, 0.65, 0.8]))
    entropy_candidates = np.unique(np.quantile(entropy, [0.35, 0.5, 0.65, 0.8, 0.9]))
    best: dict[str, float] | None = None
    best_score = -1.0
    min_coverage = max(min(target_coverage * 0.8, 0.4), 0.12)
    for top_threshold in top_candidates:
        for margin_threshold in margin_candidates:
            for entropy_threshold in entropy_candidates:
                accepted = (
                    (top_prob >= float(top_threshold))
                    & (margin >= float(margin_threshold))
                    & (entropy <= float(entropy_threshold))
                )
                coverage = float(np.mean(accepted))
                if coverage < min_coverage:
                    continue
                precision = float(np.mean(predicted[accepted] == y_true[accepted])) if np.any(accepted) else 0.0
                score = precision - (abs(coverage - target_coverage) * 0.08)
                if score > best_score:
                    best_score = score
                    best = {
                        "mode": "threshold_filters",
                        "min_top_probability": round(float(top_threshold), 6),
                        "min_margin": round(float(margin_threshold), 6),
                        "max_entropy": round(float(entropy_threshold), 6),
                        "target_coverage": round(float(target_coverage), 4),
                        "achieved_coverage": round(coverage, 4),
                        "achieved_precision": round(precision, 4),
                    }
    if best is not None:
        return best
    fallback_threshold = float(np.quantile(top_prob, max(0.0, 1.0 - target_coverage)))
    accepted = top_prob >= fallback_threshold
    coverage = float(np.mean(accepted))
    precision = float(np.mean(predicted[accepted] == y_true[accepted])) if np.any(accepted) else 0.0
    return {
        "mode": "threshold_filters",
        "min_top_probability": round(fallback_threshold, 6),
        "min_margin": 0.0,
        "max_entropy": 1.0,
        "target_coverage": round(float(target_coverage), 4),
        "achieved_coverage": round(coverage, 4),
        "achieved_precision": round(precision, 4),
    }


def evaluate_high_confidence_policy(
    probabilities: np.ndarray,
    policy: dict[str, Any],
    *,
    trade_quality: np.ndarray | None = None,
    regime_labels: np.ndarray | None = None,
) -> dict[str, np.ndarray | float]:
    probs = _normalize_probabilities(probabilities)
    if len(probs) == 0:
        return {
            "accepted": np.zeros((0,), dtype=bool),
            "top_probability": np.empty((0,), dtype=np.float64),
            "margin": np.empty((0,), dtype=np.float64),
            "entropy": np.empty((0,), dtype=np.float64),
            "score": np.empty((0,), dtype=np.float64),
            "coverage": 0.0,
        }
    top_prob = np.max(probs, axis=1)
    margin = top_two_margin(probs)
    entropy = normalized_entropy(probs)
    if str(policy.get("mode", "")).strip() == "score_rank":
        ranking_scores, _ = compute_acceptance_scores(
            probs,
            trade_quality=trade_quality,
            components=list(policy.get("components") or []),
            weights=dict(policy.get("weights") or {}),
        )
        accepted = ranking_scores >= float(policy.get("min_score", 1.0))
        regime_min_scores = {
            str(label): float(value)
            for label, value in dict(policy.get("regime_min_scores") or {}).items()
        }
        if regime_labels is not None and regime_min_scores:
            labels = np.asarray(regime_labels, dtype=object)
            thresholds = np.full(len(ranking_scores), float(policy.get("min_score", 1.0)), dtype=np.float64)
            for idx, label in enumerate(labels):
                thresholds[idx] = float(regime_min_scores.get(str(label), thresholds[idx]))
            accepted = ranking_scores >= thresholds
        score_values = ranking_scores
    else:
        accepted = (
            (top_prob >= float(policy.get("min_top_probability", 1.0)))
            & (margin >= float(policy.get("min_margin", 1.0)))
            & (entropy <= float(policy.get("max_entropy", 0.0)))
        )
        score_values = top_prob
    return {
        "accepted": accepted,
        "top_probability": top_prob,
        "margin": margin,
        "entropy": entropy,
        "score": score_values,
        "coverage": float(np.mean(accepted)),
    }


def precision_at_fixed_coverages(
    y_true: np.ndarray,
    probabilities: np.ndarray,
    net_long_returns: np.ndarray,
    net_short_returns: np.ndarray,
    *,
    coverages: tuple[float, ...] = (0.2, 0.3, 0.4),
    trade_quality: np.ndarray | None = None,
    ranking_components: list[str] | None = None,
    ranking_weights: dict[str, float] | None = None,
    regime_labels: np.ndarray | None = None,
    regime_coverage_caps: dict[str, float] | None = None,
) -> dict[str, dict[str, float]]:
    probs = _normalize_probabilities(probabilities)
    if len(y_true) == 0:
        return {}
    prediction = np.argmax(probs, axis=1)
    ranking_scores = None
    normalized_weights: dict[str, float] = {}
    if ranking_components:
        ranking_scores, normalized_weights = compute_acceptance_scores(
            probs,
            trade_quality=trade_quality,
            components=ranking_components,
            weights=ranking_weights,
        )
    results: dict[str, dict[str, float]] = {}
    for coverage in coverages:
        target = min(max(float(coverage), 0.01), 1.0)
        accepted = build_fixed_coverage_mask(
            probs,
            target,
            ranking_scores=ranking_scores,
            regime_labels=regime_labels,
            regime_coverage_caps=regime_coverage_caps,
        )
        realized_returns = np.zeros(len(prediction), dtype=np.float64)
        realized_returns[prediction == 0] = net_short_returns[prediction == 0]
        realized_returns[prediction == 2] = net_long_returns[prediction == 2]
        trade_mask = accepted & (prediction != 1)
        results[f"{int(round(target * 100))}%"] = {
            "target_coverage": round(target, 4),
            "achieved_coverage": round(float(np.mean(accepted)), 4),
            "precision": round(float(np.mean(prediction[accepted] == y_true[accepted])) if np.any(accepted) else 0.0, 4),
            "trade_precision": round(float(np.mean(realized_returns[trade_mask] > 0)) if np.any(trade_mask) else 0.0, 4),
            "trade_coverage": round(float(np.mean(trade_mask)), 4),
            "avg_net_return": round(float(np.mean(realized_returns[trade_mask])) if np.any(trade_mask) else 0.0, 6),
            "mode": "score_rank" if ranking_components else "top_probability_rank",
            "weight_summary": normalized_weights if ranking_components else {},
        }
    return results


def build_fixed_coverage_mask(
    probabilities: np.ndarray,
    coverage: float,
    *,
    ranking_scores: np.ndarray | None = None,
    regime_labels: np.ndarray | None = None,
    regime_coverage_caps: dict[str, float] | None = None,
) -> np.ndarray:
    probs = _normalize_probabilities(probabilities)
    if len(probs) == 0:
        return np.zeros((0,), dtype=bool)
    target = min(max(float(coverage), 0.01), 1.0)
    if ranking_scores is not None:
        scores = np.asarray(ranking_scores, dtype=np.float64)
        if regime_labels is not None and regime_coverage_caps:
            return build_regime_capped_coverage_mask(
                scores,
                target,
                regime_labels=np.asarray(regime_labels, dtype=object),
                regime_coverage_caps=regime_coverage_caps,
            )
    else:
        scores = np.max(probs, axis=1)
    order = np.argsort(-scores, kind="mergesort")
    keep_count = min(len(probs), max(1, int(np.ceil(len(probs) * target))))
    accepted = np.zeros(len(probs), dtype=bool)
    accepted[order[:keep_count]] = True
    return accepted


def search_acceptance_score_weights(
    probabilities: np.ndarray,
    y_true: np.ndarray,
    net_long_returns: np.ndarray,
    net_short_returns: np.ndarray,
    *,
    components: list[str],
    target_coverage: float,
    trade_quality: np.ndarray | None = None,
    regime_labels: np.ndarray | None = None,
    regime_coverage_caps: dict[str, float] | None = None,
    seeded_weights: dict[str, float] | None = None,
) -> tuple[dict[str, float], dict[str, float]]:
    selected_components = [str(component).strip() for component in list(components or []) if str(component).strip()]
    if not selected_components:
        return {}, {"precision": 0.0, "trade_precision": 0.0, "coverage": 0.0, "score": 0.0}
    candidate_levels = (0.0, 0.25, 0.5, 0.75, 1.0)
    candidate_weight_sets: list[dict[str, float]] = []
    seen: set[tuple[tuple[str, float], ...]] = set()
    for combo in product(candidate_levels, repeat=len(selected_components)):
        if sum(combo) <= 0:
            continue
        candidate = _normalize_score_weights(
            selected_components,
            {component: combo[idx] for idx, component in enumerate(selected_components)},
        )
        fingerprint = tuple(sorted(candidate.items()))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        candidate_weight_sets.append(candidate)
    if seeded_weights:
        candidate = _normalize_score_weights(selected_components, seeded_weights)
        fingerprint = tuple(sorted(candidate.items()))
        if fingerprint not in seen:
            candidate_weight_sets.insert(0, candidate)
            seen.add(fingerprint)
    best_weights = _normalize_score_weights(selected_components, seeded_weights)
    best_metrics = {"precision": 0.0, "trade_precision": 0.0, "coverage": 0.0, "score": float("-inf")}
    prediction = np.argmax(_normalize_probabilities(probabilities), axis=1)
    for candidate in candidate_weight_sets:
        scores, normalized_weights = compute_acceptance_scores(
            probabilities,
            trade_quality=trade_quality,
            components=selected_components,
            weights=candidate,
        )
        accepted = build_fixed_coverage_mask(
            probabilities,
            target_coverage,
            ranking_scores=scores,
            regime_labels=regime_labels,
            regime_coverage_caps=regime_coverage_caps,
        )
        coverage = float(np.mean(accepted)) if len(accepted) else 0.0
        precision = float(np.mean(prediction[accepted] == y_true[accepted])) if np.any(accepted) else 0.0
        realized_returns = np.zeros(len(prediction), dtype=np.float64)
        realized_returns[prediction == 0] = net_short_returns[prediction == 0]
        realized_returns[prediction == 2] = net_long_returns[prediction == 2]
        trade_mask = accepted & (prediction != 1)
        trade_precision = float(np.mean(realized_returns[trade_mask] > 0)) if np.any(trade_mask) else 0.0
        avg_net_return = float(np.mean(realized_returns[trade_mask])) if np.any(trade_mask) else 0.0
        objective = precision + (0.15 * trade_precision) + (0.05 * max(avg_net_return, 0.0)) - (0.05 * abs(coverage - target_coverage))
        if objective > best_metrics["score"]:
            best_weights = normalized_weights
            best_metrics = {
                "precision": round(precision, 4),
                "trade_precision": round(trade_precision, 4),
                "coverage": round(coverage, 4),
                "avg_net_return": round(avg_net_return, 6),
                "score": round(objective, 6),
            }
    return best_weights, best_metrics


def summarize_regime_metrics(
    y_true: np.ndarray,
    probabilities: np.ndarray,
    regime_labels: np.ndarray,
    net_long_returns: np.ndarray,
    net_short_returns: np.ndarray,
    *,
    accepted_mask: np.ndarray | None = None,
) -> dict[str, Any]:
    probs = _normalize_probabilities(probabilities)
    if len(y_true) == 0:
        return {"by_regime": {}, "precision_std": 0.0, "precision_range": 0.0}
    accepted = np.asarray(accepted_mask, dtype=bool) if accepted_mask is not None else np.ones(len(y_true), dtype=bool)
    prediction = np.argmax(probs, axis=1)
    realized_returns = np.zeros(len(prediction), dtype=np.float64)
    realized_returns[prediction == 0] = net_short_returns[prediction == 0]
    realized_returns[prediction == 2] = net_long_returns[prediction == 2]
    by_regime: dict[str, dict[str, float]] = {}
    precisions: list[float] = []
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
        return {"by_regime": by_regime, "precision_std": 0.0, "precision_range": 0.0}
    return {
        "by_regime": by_regime,
        "precision_std": round(float(np.std(precisions)), 6),
        "precision_range": round(float(max(precisions) - min(precisions)), 6),
    }


def feature_value(columns: dict[str, np.ndarray], name: str, index: int) -> float:
    values = columns.get(name)
    if values is None:
        return 0.0
    try:
        value = float(values[index])
    except Exception:
        return 0.0
    if not np.isfinite(value):
        return 0.0
    return value
