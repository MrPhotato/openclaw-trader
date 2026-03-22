from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib


def artifact_paths(artifact_root: Path, coin: str, horizon: str) -> dict[str, Path]:
    base = artifact_root / coin.upper() / horizon
    return {
        "meta": base / "meta.json",
        "regime": base / "regime.joblib",
        "classifier": base / "classifier.joblib",
        "calibration_json": base / "calibration-report.json",
        "calibration_md": base / "calibration-report.md",
    }


def save_training_payload(
    artifact_root: Path,
    *,
    coin: str,
    horizon: str,
    payload: dict[str, Any],
    report_payload: dict[str, Any],
    report_markdown: str,
) -> dict[str, Any]:
    paths = artifact_paths(artifact_root, coin, horizon)
    paths["meta"].parent.mkdir(parents=True, exist_ok=True)
    paths["meta"].write_text(json.dumps(payload["meta"], ensure_ascii=False, indent=2))
    joblib.dump(payload["regime"], paths["regime"])
    joblib.dump(payload["classifier"], paths["classifier"])
    paths["calibration_json"].write_text(json.dumps(report_payload, ensure_ascii=False, indent=2))
    paths["calibration_md"].write_text(report_markdown)
    return payload


def load_artifact_payload(artifact_root: Path, *, coin: str, horizon: str) -> dict[str, Any]:
    paths = artifact_paths(artifact_root, coin, horizon)
    return {
        "meta": json.loads(paths["meta"].read_text()),
        "regime": joblib.load(paths["regime"]),
        "classifier": joblib.load(paths["classifier"]),
    }
