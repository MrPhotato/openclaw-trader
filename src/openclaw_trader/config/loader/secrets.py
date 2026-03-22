from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values

from ..models import CoinbaseCredentials
from .paths import build_paths, runtime_root


def load_coinbase_credentials(runtime_root_path: Path | None = None) -> CoinbaseCredentials:
    paths = build_paths(runtime_root_path or runtime_root())
    values = dotenv_values(paths.secrets_file)
    api_key_id = str(values.get("COINBASE_API_KEY_ID") or "").strip()
    api_key_secret = str(values.get("COINBASE_API_KEY_SECRET") or "").strip()
    api_base = str(values.get("COINBASE_API_BASE") or "https://api.coinbase.com").strip()
    if not api_key_id or not api_key_secret:
        raise ValueError(f"Coinbase credentials missing in {paths.secrets_file}")
    return CoinbaseCredentials(
        api_key_id=api_key_id,
        api_key_secret=api_key_secret,
        api_base=api_base,
    )


def safe_coinbase_credentials(paths) -> CoinbaseCredentials | None:
    try:
        return load_coinbase_credentials(paths.runtime_root)
    except Exception:
        return None
