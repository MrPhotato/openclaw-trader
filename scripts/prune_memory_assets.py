#!/usr/bin/env python3
"""Offline bulk-prune for memory_assets.

Use this when MemoryAssetsRetentionMonitor's `backlog_too_large_skip` guard
would prevent the in-process monitor from clearing a multi-month backlog.
Trader must be stopped before running — this opens a non-WAL connection
and runs a long DELETE per type that would block live writers.

Reads the same retention policy block from `~/.openclaw-trader/config/dispatch.yaml`
that the runtime monitor uses, so there is exactly one source of truth.

Usage:
    .venv/bin/python scripts/prune_memory_assets.py [--dry-run] [--db PATH]
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

DEFAULT_DB = Path("/Users/chenzian/.openclaw-trader/state/trader_v2.db")
DEFAULT_CONFIG = Path("/Users/chenzian/.openclaw-trader/config/dispatch.yaml")
_TTL_PATTERN = re.compile(r"^\s*(\d+)\s*([smhd])\s*$", re.IGNORECASE)
_TTL_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_ttl(spec: str | int | float) -> int:
    if isinstance(spec, (int, float)):
        return max(0, int(spec))
    match = _TTL_PATTERN.match(str(spec))
    if match is None:
        raise ValueError(f"unparseable TTL spec: {spec!r}")
    return int(match.group(1)) * _TTL_UNITS[match.group(2).lower()]


def load_policies(config_path: Path) -> dict[str, int]:
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    raw = payload.get("memory_retention_policies") or {}
    return {str(k): parse_ttl(v) for k, v in raw.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dry-run", action="store_true", help="report only, no DELETE")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"db not found: {args.db}")
        return 1
    policies = load_policies(args.config)
    if not policies:
        print(f"no memory_retention_policies block in {args.config}")
        return 1

    now = datetime.now(UTC)
    print(f"prune_memory_assets db={args.db} dry_run={args.dry_run} now={now.isoformat()}")
    print(f"  {len(policies)} policies loaded from {args.config.name}")

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    total_deleted = 0
    try:
        for asset_type, ttl_seconds in sorted(policies.items()):
            cutoff = (now - timedelta(seconds=ttl_seconds)).isoformat()
            before_row = conn.execute(
                "SELECT COUNT(*) FROM assets WHERE asset_type = ?", (asset_type,)
            ).fetchone()
            before = int(before_row[0]) if before_row else 0
            if before == 0:
                continue
            stale_row = conn.execute(
                "SELECT COUNT(*) FROM assets WHERE asset_type = ? AND created_at < ?",
                (asset_type, cutoff),
            ).fetchone()
            stale = int(stale_row[0]) if stale_row else 0
            print(
                f"  {asset_type:36s}  ttl={ttl_seconds//86400 if ttl_seconds>=86400 else ttl_seconds//3600:>4}{'d' if ttl_seconds>=86400 else 'h'}"
                f"  rows={before:>7}  stale={stale:>7}"
            )
            if not args.dry_run and stale > 0:
                cursor = conn.execute(
                    "DELETE FROM assets WHERE asset_type = ? AND created_at < ?",
                    (asset_type, cutoff),
                )
                deleted = int(cursor.rowcount or 0)
                total_deleted += deleted
                conn.commit()
        if not args.dry_run:
            print(f"\ntotal deleted: {total_deleted}")
            print("running VACUUM to reclaim disk space (this may take a while)...")
            conn.execute("VACUUM")
            print("vacuum complete")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
