#!/usr/bin/env python3
"""MEA-facing wrapper over the vendored `digital-oracle` skill.

Runs a set of market-data providers in parallel via digital-oracle's
`gather()` helper and emits structured JSON. Intended to be called by MEA
from its `exec` tool during the "market-price reality check" step in
`skills/mea-event-review/references/search-playbook.md`.

Presets cover the scenarios MEA actually hits day to day. For ad-hoc
mixes use `--signals k1=preset_key,...` or `--file spec.json`.

Usage:
    python3 scripts/digital_oracle_query.py --preset oil_geopolitics
    python3 scripts/digital_oracle_query.py --preset crypto_regime
    python3 scripts/digital_oracle_query.py --preset recession_risk
    python3 scripts/digital_oracle_query.py --preset hormuz_brent_now
    python3 scripts/digital_oracle_query.py --list-presets
    python3 scripts/digital_oracle_query.py --signals btc_basis,crude_cot,fng
    python3 scripts/digital_oracle_query.py --file /tmp/spec.json

Output is a single JSON object on stdout:
    {"preset": "...", "elapsed_seconds": 1.78,
     "signals": {"key": {"ok": true, "data": <provider payload>}, ...}}

Provider failures are isolated — one broken endpoint does not abort the
whole gather. Each signal carries its own `ok` / `error` fields.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT / "skills" / "digital-oracle"
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from digital_oracle import (  # noqa: E402  (after sys.path munging)
    BisProvider,
    BisRateQuery,
    CftcCotProvider,
    CftcCotQuery,
    CMEFedWatchProvider,
    CoinGeckoPriceQuery,
    CoinGeckoProvider,
    DeribitFuturesCurveQuery,
    DeribitProvider,
    EdgarInsiderQuery,
    EdgarProvider,
    FearGreedProvider,
    KalshiMarketQuery,
    KalshiProvider,
    PolymarketEventQuery,
    PolymarketProvider,
    PriceHistoryQuery,
    USTreasuryProvider,
    WebSearchProvider,
    WorldBankProvider,
    WorldBankQuery,
    YahooPriceProvider,
    gather,
)


# Single-provider builders. Each factory returns a callable with no args.
# Keeping them as lambdas means they instantiate the provider lazily, so a
# broken `import` in one provider does not kill the others at module load.
SIGNALS: dict[str, Callable[[], Any]] = {
    # --- Prediction markets ---
    "polymarket_iran": lambda: PolymarketProvider().list_events(
        PolymarketEventQuery(slug_contains="iran", limit=5)
    ),
    "polymarket_hormuz": lambda: PolymarketProvider().list_events(
        PolymarketEventQuery(slug_contains="hormuz", limit=5)
    ),
    "polymarket_oil": lambda: PolymarketProvider().list_events(
        PolymarketEventQuery(slug_contains="oil", limit=5)
    ),
    "polymarket_recession": lambda: PolymarketProvider().list_events(
        PolymarketEventQuery(slug_contains="recession", limit=5)
    ),
    "kalshi_fed": lambda: KalshiProvider().list_markets(
        KalshiMarketQuery(series_ticker="KXFED", limit=10)
    ),
    # --- Institutional positioning ---
    "crude_cot": lambda: CftcCotProvider().list_reports(
        CftcCotQuery(commodity_name="CRUDE OIL", limit=4)
    ),
    "gold_cot": lambda: CftcCotProvider().list_reports(
        CftcCotQuery(commodity_name="GOLD", limit=4)
    ),
    "sp500_cot": lambda: CftcCotProvider().list_reports(
        CftcCotQuery(commodity_name="S&P 500", limit=4)
    ),
    "copper_cot": lambda: CftcCotProvider().list_reports(
        CftcCotQuery(commodity_name="COPPER", limit=4)
    ),
    # --- Crypto derivatives & spot ---
    "btc_basis": lambda: DeribitProvider().get_futures_term_structure(
        DeribitFuturesCurveQuery(currency="BTC")
    ),
    "eth_basis": lambda: DeribitProvider().get_futures_term_structure(
        DeribitFuturesCurveQuery(currency="ETH")
    ),
    "crypto_spot": lambda: CoinGeckoProvider().get_prices(
        CoinGeckoPriceQuery(coin_ids=("bitcoin", "ethereum"))
    ),
    # --- Macro anchors ---
    "us_yield_curve": lambda: USTreasuryProvider().latest_yield_curve(),
    "fedwatch": lambda: CMEFedWatchProvider().get_probabilities(),
    "fng": lambda: FearGreedProvider().get_index(),
    # --- Safe haven / risk ratios ---
    "gold_price": lambda: YahooPriceProvider().get_history(
        PriceHistoryQuery(symbol="GC=F", limit=30)
    ),
    "copper_price": lambda: YahooPriceProvider().get_history(
        PriceHistoryQuery(symbol="HG=F", limit=30)
    ),
    "brent_price": lambda: YahooPriceProvider().get_history(
        PriceHistoryQuery(symbol="BZ=F", limit=30)
    ),
    "wti_price": lambda: YahooPriceProvider().get_history(
        PriceHistoryQuery(symbol="CL=F", limit=30)
    ),
    "dxy": lambda: YahooPriceProvider().get_history(
        PriceHistoryQuery(symbol="DX-Y.NYB", limit=30)
    ),
    "spy": lambda: YahooPriceProvider().get_history(
        PriceHistoryQuery(symbol="SPY", limit=30)
    ),
    # --- Central bank & insider ---
    "bis_us_cn_rates": lambda: BisProvider().get_policy_rates(
        BisRateQuery(countries=("US", "CN"), start_year=2024)
    ),
    # --- Misc web search escape hatch (VIX/MOVE/CDS/BDI/TTF not in APIs) ---
    "vix_search": lambda: WebSearchProvider().search("VIX index current level"),
    "move_search": lambda: WebSearchProvider().search("MOVE index bond volatility today"),
}


PRESETS: dict[str, tuple[str, list[str]]] = {
    # Presets deliberately avoid Yahoo-backed signals by default because
    # runtime_pack.macro_prices already carries Brent / WTI / DXY / US10Y /
    # F&G / BTC ETF activity, and the yfinance Python library adds 8-10s of
    # startup overhead per call. Use `--signals brent_price,gold_price,...`
    # if you need extra Yahoo history on top.
    "oil_geopolitics": (
        "Brent / WTI regime + Iran/Hormuz war risk. Use when news is about "
        "ceasefire / conflict / strait closures / oil sanctions. Pairs with "
        "runtime_pack.macro_prices.brent (yfinance mark) for the live price.",
        [
            "polymarket_iran",
            "polymarket_hormuz",
            "polymarket_oil",
            "crude_cot",
            "gold_cot",
            "btc_basis",  # crypto risk-on/off proxy
            "fng",
        ],
    ),
    "crypto_regime": (
        "Pure crypto regime read: BTC/ETH basis + spot + curve + sentiment. "
        "Use when the event's first-order impact is on BTC/ETH structure.",
        [
            "btc_basis",
            "eth_basis",
            "crypto_spot",
            "fng",
            "us_yield_curve",
        ],
    ),
    "recession_risk": (
        "Macro cycle read: curve + Fed path + institutional positioning + "
        "recession contracts. Use for macro data surprises (CPI, PCE, NFP, GDP).",
        [
            "us_yield_curve",
            "fedwatch",
            "polymarket_recession",
            "copper_cot",
            "sp500_cot",
            "gold_cot",
            "fng",
            "bis_us_cn_rates",
        ],
    ),
    "hormuz_brent_now": (
        "Minimal fast preset for the recurring Brent / Hormuz loop — 3 signals, "
        "~1-2s. Use when RT is already asking about Brent validity. Brent price "
        "itself lives in runtime_pack.macro_prices.brent.",
        [
            "polymarket_hormuz",
            "crude_cot",
            "fng",
        ],
    ),
    "stock_crash_risk": (
        "US equity crash / drawdown read. Use when the question is 'will SPY drop'. "
        "VIX / MOVE arrive via web_search since no free structured API exists.",
        [
            "sp500_cot",
            "us_yield_curve",
            "fng",
            "vix_search",
            "move_search",
        ],
    ),
}


def _to_jsonable(value: Any) -> Any:
    """Best-effort conversion of provider return payloads to JSON."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if is_dataclass(value):
        return {k: _to_jsonable(v) for k, v in asdict(value).items()}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_to_jsonable(v) for v in value]
    if hasattr(value, "__dict__"):
        return {k: _to_jsonable(v) for k, v in vars(value).items() if not k.startswith("_")}
    return repr(value)


def run(signal_keys: list[str]) -> dict[str, Any]:
    """Execute the selected signals concurrently and return a serializable dict."""
    unknown = [k for k in signal_keys if k not in SIGNALS]
    if unknown:
        raise SystemExit(f"unknown signal keys: {unknown}. Use --list-signals to see available.")

    factories = {k: SIGNALS[k] for k in signal_keys}
    t0 = time.perf_counter()
    bag = gather(factories)
    elapsed = time.perf_counter() - t0

    signals: dict[str, Any] = {}
    for key in signal_keys:
        raw = bag.get_or(key, None)
        error = bag.errors.get(key) if hasattr(bag, "errors") else None
        signals[key] = {
            "ok": raw is not None and error is None,
            "error": str(error) if error else None,
            "data": _to_jsonable(raw),
        }
    return {
        "elapsed_seconds": round(elapsed, 3),
        "signal_count": len(signal_keys),
        "signals": signals,
    }


def _parse_spec_file(path: str) -> list[str]:
    with open(path) as fp:
        spec = json.load(fp)
    if isinstance(spec, dict) and "signals" in spec:
        return list(spec["signals"])
    if isinstance(spec, list):
        return list(spec)
    raise SystemExit("spec file must be a list or {signals: [...]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--preset", help=f"preset name; one of: {', '.join(PRESETS.keys())}")
    group.add_argument("--signals", help="comma-separated list of signal keys")
    group.add_argument("--file", help="JSON file containing a list or {signals: [...]}")
    group.add_argument("--list-presets", action="store_true", help="print preset names + blurb + signals")
    group.add_argument("--list-signals", action="store_true", help="print available signal keys")
    parser.add_argument("--indent", type=int, default=2, help="JSON indent (default 2; 0 = single line)")
    args = parser.parse_args()

    if args.list_presets:
        for name, (blurb, sigs) in PRESETS.items():
            print(f"{name}")
            print(f"  {blurb}")
            print(f"  signals: {sigs}")
            print()
        return
    if args.list_signals:
        for key in sorted(SIGNALS):
            print(key)
        return

    if args.preset:
        if args.preset not in PRESETS:
            raise SystemExit(f"unknown preset: {args.preset}. Known: {list(PRESETS.keys())}")
        signal_keys = PRESETS[args.preset][1]
        header = {"preset": args.preset, "preset_blurb": PRESETS[args.preset][0]}
    elif args.signals:
        signal_keys = [s.strip() for s in args.signals.split(",") if s.strip()]
        header = {"preset": None, "signals_requested": signal_keys}
    elif args.file:
        signal_keys = _parse_spec_file(args.file)
        header = {"preset": None, "file": args.file}
    else:
        parser.error("one of --preset / --signals / --file / --list-* is required")

    result = run(signal_keys)
    out = {**header, **result}
    indent = args.indent if args.indent > 0 else None
    json.dump(out, sys.stdout, indent=indent, default=str, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
