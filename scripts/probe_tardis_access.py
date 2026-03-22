from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


TARDIS_DATASET_BASE = "https://datasets.tardis.dev/v1"
EXCHANGE = "binance-futures"
DATASET = "derivative_ticker"


def _probe(symbol: str, *, day: datetime) -> dict[str, Any]:
    url = f"{TARDIS_DATASET_BASE}/{EXCHANGE}/{DATASET}/{day:%Y/%m/%d}/{symbol.upper()}.csv.gz"
    response = httpx.get(
        url,
        timeout=45.0,
        follow_redirects=True,
        headers={"User-Agent": "openclaw-trader/tardis-probe"},
    )
    body: Any = None
    if response.status_code >= 400:
        try:
            body = response.json()
        except Exception:
            body = response.text[:500]
    return {
        "symbol": symbol.upper(),
        "date": f"{day:%Y-%m-%d}",
        "url": url,
        "status_code": response.status_code,
        "content_length": len(response.content),
        "body": body,
    }


def _verdict(probes: list[dict[str, Any]]) -> dict[str, Any]:
    by_name = {(item["symbol"], item["date"]): item for item in probes}
    sample = by_name.get(("BTCUSDT", "2020-02-01"))
    recent_monthly = by_name.get(("BTCUSDT", "2025-01-01"))
    non_monthly = by_name.get(("BTCUSDT", "2025-01-02"))
    eth_monthly = by_name.get(("ETHUSDT", "2024-12-01"))

    if sample and sample["status_code"] == 200 and recent_monthly and recent_monthly["status_code"] == 200:
        if non_monthly and non_monthly["status_code"] == 401:
            return {
                "mode": "monthly_public_only",
                "conclusion": "Public Tardis access works for first-day-of-month files, but non-monthly daily history requires an API key.",
                "eth_monthly_status": eth_monthly["status_code"] if eth_monthly else None,
            }
        return {
            "mode": "public_access_unclear",
            "conclusion": "Monthly public files are reachable, but non-monthly behavior did not match the expected 401 pattern.",
            "eth_monthly_status": eth_monthly["status_code"] if eth_monthly else None,
        }
    if non_monthly and non_monthly["status_code"] == 401:
        return {
            "mode": "api_key_required",
            "conclusion": "Tardis rejected non-monthly daily history without an API key.",
            "eth_monthly_status": eth_monthly["status_code"] if eth_monthly else None,
        }
    return {
        "mode": "path_or_coverage_problem",
        "conclusion": "The probed Tardis path did not expose the expected monthly public files; treat the current path as unverified.",
        "eth_monthly_status": eth_monthly["status_code"] if eth_monthly else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe public Tardis dataset accessibility for derivative_ticker history.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    probes = [
        _probe("BTCUSDT", day=datetime(2020, 2, 1, tzinfo=UTC)),
        _probe("BTCUSDT", day=datetime(2025, 1, 1, tzinfo=UTC)),
        _probe("BTCUSDT", day=datetime(2025, 1, 2, tzinfo=UTC)),
        _probe("ETHUSDT", day=datetime(2024, 12, 1, tzinfo=UTC)),
        _probe("SOLUSDT", day=datetime(2025, 1, 1, tzinfo=UTC)),
    ]
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "exchange": EXCHANGE,
        "dataset": DATASET,
        "probes": probes,
        "verdict": _verdict(probes),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(json.dumps({"output": str(args.output), "verdict": payload["verdict"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
