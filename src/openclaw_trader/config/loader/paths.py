from __future__ import annotations

import os
from pathlib import Path

from ..models import RuntimePaths


def runtime_root() -> Path:
    return Path(
        os.getenv(
            "OPENCLAW_V2_RUNTIME_ROOT",
            os.getenv("OPENCLAW_RUNTIME_ROOT", str(Path.home() / ".openclaw-trader")),
        )
    ).expanduser()


def build_paths(root: Path) -> RuntimePaths:
    return RuntimePaths(
        runtime_root=root,
        config_dir=root / "config",
        state_dir=root / "state",
        data_dir=root / "data",
        log_dir=root / "logs",
        report_dir=root / "reports",
        run_dir=root / "run",
        model_dir=root / "models",
        secrets_file=root / "secrets" / "coinbase.env",
    )
