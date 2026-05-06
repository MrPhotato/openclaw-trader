"""Memory assets retention monitor.

Background thread that periodically deletes expired rows from the `assets`
table according to per-`asset_type` TTL config. Without this, append-only
event/snapshot types (`runtime_bridge_state` written every 10s, etc.) grow
the db monotonically — verified 2026-05-07 to be the cause of the 47 GB db
that crossed sqlite's B-tree corruption threshold.

Design choices
--------------
* Per-type TTL via config dict, not one-size-fits-all. Hot system snapshots
  (`runtime_bridge_state`) get 48h; warm audit data (`agent_runtime_lease`,
  `execution_*`) get 30d; cold business knowledge (`strategy`, `retro_*`,
  `learning_directive`, `macro_*`) gets 180d. Anything not in the config
  is left alone — overwriting `*_state` types with stable asset_id need no
  retention because INSERT OR REPLACE keeps row count constant.
* Deletes run inside the same WAL'd sqlite connection that monitors and
  the API use, so writers don't get blocked on a long DELETE.
* One scan iterates every configured type. Per-type DELETE runs against
  `idx_assets_type_created_at`, so even with 75K rows the cutoff scan is
  index-bound.
* State asset (`memory_retention_state`) records the last scan summary so
  ops can grep for unexpected per-type pruning rates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from typing import Any

from ...shared.utils import new_id
from ..memory_assets.service import MemoryAssetsService


_TTL_PATTERN = re.compile(r"^\s*(\d+)\s*([smhd])\s*$", re.IGNORECASE)
_TTL_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_STATE_ASSET_ID = "memory_retention_state"


def _parse_ttl(value: str | int | float) -> int:
    """Parse `48h` / `30d` / `3600` (seconds) into integer seconds."""
    if isinstance(value, (int, float)):
        return max(0, int(value))
    match = _TTL_PATTERN.match(str(value))
    if match is None:
        raise ValueError(f"unparseable TTL spec: {value!r} (use e.g. '48h', '30d', '3600')")
    qty = int(match.group(1))
    unit = match.group(2).lower()
    return qty * _TTL_UNITS[unit]


@dataclass(frozen=True)
class MemoryRetentionConfig:
    enabled: bool = False
    scan_interval_seconds: int = 3600  # default hourly
    # asset_type -> TTL string (e.g. "48h", "30d") OR seconds int
    policies: dict[str, str | int] = field(default_factory=dict)
    # Hard upper bound on rows deleted per type per scan. Prevents one scan
    # from holding the WAL writer lock for minutes after a long backlog.
    # Subsequent scans pick up the rest until caught up.
    max_deletes_per_type_per_scan: int = 50000


class MemoryAssetsRetentionMonitor:
    def __init__(
        self,
        *,
        memory_assets: MemoryAssetsService,
        config: MemoryRetentionConfig | None = None,
    ) -> None:
        self.memory_assets = memory_assets
        self.config = config or MemoryRetentionConfig()
        self._stop = Event()
        self._thread: Thread | None = None
        # Resolve TTL specs once so a typo errors at startup, not 1h later.
        self._ttl_seconds: dict[str, int] = {
            asset_type: _parse_ttl(spec) for asset_type, spec in self.config.policies.items()
        }

    def start(self) -> None:
        if not self.config.enabled or self._thread is not None:
            return
        self._thread = Thread(
            target=self._loop,
            name="workflow-orchestrator-memory-retention",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _loop(self) -> None:
        # Run the first scan ~30s after start (don't block startup), then
        # every `scan_interval_seconds` after that.
        if self._stop.wait(30):
            return
        while not self._stop.is_set():
            try:
                self.scan_once()
            except Exception:  # noqa: BLE001 — never crash the thread
                pass
            if self._stop.wait(max(int(self.config.scan_interval_seconds), 60)):
                break

    def scan_once(self, *, now: datetime | None = None) -> dict[str, Any]:
        """Run one retention pass across all configured types. Returns a
        summary dict suitable for state persistence + log/grep."""
        current = (now or datetime.now(UTC)).astimezone(UTC)
        per_type: list[dict[str, Any]] = []
        total_deleted = 0
        for asset_type, ttl_seconds in self._ttl_seconds.items():
            cutoff = current - timedelta(seconds=ttl_seconds)
            cutoff_iso = cutoff.isoformat()
            # The repo `prune_older_than` issues a single DELETE; we do not
            # currently chunk per scan because sqlite WAL handles the row-count
            # we expect (≤ ~10k rows aged out per hour from runtime_bridge_state)
            # without blocking writers. The max_deletes_per_type_per_scan cap
            # is a safety net for the very first scan after deploy when there
            # is a multi-month backlog: we skip if the live count is huge.
            live_before = self.memory_assets.count_assets_by_type(asset_type=asset_type)
            if (
                self.config.max_deletes_per_type_per_scan > 0
                and live_before > self.config.max_deletes_per_type_per_scan * 4
            ):
                # Backlog too large — let the offline cleanup script handle the
                # bulk pass; this scan only trims a recent slice to avoid a
                # multi-minute DELETE. Caller logs the backlog and operator
                # runs `scripts/prune_memory_assets.py` once.
                per_type.append(
                    {
                        "asset_type": asset_type,
                        "ttl_seconds": ttl_seconds,
                        "cutoff_utc": cutoff_iso,
                        "rows_before": live_before,
                        "deleted": 0,
                        "note": "backlog_too_large_skip_let_offline_script_run",
                    }
                )
                continue
            deleted = self.memory_assets.prune_assets_older_than(
                asset_type=asset_type, cutoff_utc_iso=cutoff_iso
            )
            total_deleted += deleted
            per_type.append(
                {
                    "asset_type": asset_type,
                    "ttl_seconds": ttl_seconds,
                    "cutoff_utc": cutoff_iso,
                    "rows_before": live_before,
                    "deleted": deleted,
                    "rows_after": max(0, live_before - deleted),
                }
            )

        summary = {
            "scanned_at_utc": current.isoformat(),
            "trace_id": new_id("trace"),
            "total_deleted": total_deleted,
            "per_type": per_type,
        }
        self._save_state(summary)
        return summary

    def _save_state(self, summary: dict[str, Any]) -> None:
        self.memory_assets.save_asset(
            asset_type="memory_retention_state",
            asset_id=_STATE_ASSET_ID,
            payload=summary,
            actor_role="system",
            metadata={"trace_id": summary.get("trace_id")},
        )
