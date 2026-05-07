"""Tests for MemoryAssetsRetentionMonitor (added 2026-05-07).

Covers:
- TTL parser accepts `48h` / `30d` / int seconds; rejects garbage
- Monitor deletes rows older than TTL for configured asset_types only
- Monitor leaves rows newer than TTL alone
- Monitor leaves unconfigured asset_types alone (state types are unconfigured
  by design — they overwrite same asset_id and never accumulate)
- Monitor handles backlog-too-large guard (defers to offline script)
- Monitor records its own state asset (`memory_retention_state`) on each scan
- Monitor returns a per-type summary the caller can grep
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from openclaw_trader.modules.workflow_orchestrator.memory_retention import (
    MemoryAssetsRetentionMonitor,
    MemoryRetentionConfig,
    _parse_ttl,
)

from tests.helpers_v2 import build_test_harness


class TtlParserTests(unittest.TestCase):
    def test_parse_seconds_int(self) -> None:
        self.assertEqual(_parse_ttl(3600), 3600)

    def test_parse_hours(self) -> None:
        self.assertEqual(_parse_ttl("48h"), 48 * 3600)

    def test_parse_days(self) -> None:
        self.assertEqual(_parse_ttl("30d"), 30 * 86400)
        self.assertEqual(_parse_ttl("180d"), 180 * 86400)

    def test_parse_minutes_seconds(self) -> None:
        self.assertEqual(_parse_ttl("15m"), 900)
        self.assertEqual(_parse_ttl("60s"), 60)

    def test_parse_garbage_raises(self) -> None:
        for bad in ["", "abc", "3x", "48 hours"]:
            with self.assertRaises(ValueError):
                _parse_ttl(bad)


class MemoryRetentionMonitorTests(unittest.TestCase):
    def _seed_assets(self, harness, asset_type: str, ages_hours: list[float]) -> list[str]:
        """Insert rows of the given asset_type with controlled created_at times.
        Returns the list of asset_ids in order."""
        ids: list[str] = []
        now = datetime.now(UTC)
        for age_h in ages_hours:
            asset_id = f"{asset_type}_{len(ids)}"
            harness.container.memory_assets.save_asset(
                asset_type=asset_type,
                asset_id=asset_id,
                payload={"seq": len(ids)},
                actor_role="system",
            )
            # Override created_at to the desired age (default save_asset uses now)
            with harness.container.memory_assets.repository.database.connect() as conn:
                target_ts = (now - timedelta(hours=age_h)).isoformat()
                conn.execute(
                    "UPDATE assets SET created_at = ? WHERE asset_id = ?",
                    (target_ts, asset_id),
                )
            ids.append(asset_id)
        return ids

    def test_monitor_deletes_rows_older_than_ttl(self) -> None:
        harness = build_test_harness()
        try:
            # 5 rows: 100h, 80h, 30h, 10h, 1h old. TTL=48h → delete first two.
            ids = self._seed_assets(
                harness, "runtime_bridge_state", [100.0, 80.0, 30.0, 10.0, 1.0]
            )
            monitor = MemoryAssetsRetentionMonitor(
                memory_assets=harness.container.memory_assets,
                config=MemoryRetentionConfig(
                    enabled=True, policies={"runtime_bridge_state": "48h"}
                ),
            )
            summary = monitor.scan_once()

            self.assertEqual(summary["total_deleted"], 2)
            self.assertEqual(len(summary["per_type"]), 1)
            entry = summary["per_type"][0]
            self.assertEqual(entry["asset_type"], "runtime_bridge_state")
            self.assertEqual(entry["deleted"], 2)
            self.assertEqual(entry["rows_before"], 5)
            self.assertEqual(entry["rows_after"], 3)
            # Verify the surviving rows are exactly the newer 3
            for survivor_id in ids[2:]:
                self.assertIsNotNone(harness.container.memory_assets.get_asset(survivor_id))
            for deleted_id in ids[:2]:
                self.assertIsNone(harness.container.memory_assets.get_asset(deleted_id))
        finally:
            harness.cleanup()

    def test_monitor_leaves_unconfigured_types_alone(self) -> None:
        """State asset types (asset_id stable, never accumulate) are NOT in
        the policy config. Verify the monitor doesn't touch them — even if
        an old row happens to exist, it stays."""
        harness = build_test_harness()
        try:
            self._seed_assets(harness, "rt_trigger_event", [100.0, 1.0])
            self._seed_assets(harness, "risk_brake_state", [100.0, 1.0])
            monitor = MemoryAssetsRetentionMonitor(
                memory_assets=harness.container.memory_assets,
                # Only rt_trigger_event has a TTL; risk_brake_state is unconfigured.
                config=MemoryRetentionConfig(
                    enabled=True, policies={"rt_trigger_event": "48h"}
                ),
            )
            summary = monitor.scan_once()
            self.assertEqual(summary["total_deleted"], 1)
            type_in_summary = [e["asset_type"] for e in summary["per_type"]]
            # risk_brake_state should NOT appear at all in the summary
            self.assertIn("rt_trigger_event", type_in_summary)
            self.assertNotIn("risk_brake_state", type_in_summary)
            # And both risk_brake_state rows should still exist
            self.assertEqual(
                harness.container.memory_assets.count_assets_by_type(
                    asset_type="risk_brake_state"
                ),
                2,
            )
        finally:
            harness.cleanup()

    def test_monitor_handles_no_matches(self) -> None:
        """All rows are within TTL — nothing deleted, but summary still reported."""
        harness = build_test_harness()
        try:
            self._seed_assets(harness, "runtime_bridge_state", [10.0, 5.0, 1.0])
            monitor = MemoryAssetsRetentionMonitor(
                memory_assets=harness.container.memory_assets,
                config=MemoryRetentionConfig(
                    enabled=True, policies={"runtime_bridge_state": "48h"}
                ),
            )
            summary = monitor.scan_once()
            self.assertEqual(summary["total_deleted"], 0)
            self.assertEqual(summary["per_type"][0]["deleted"], 0)
            self.assertEqual(summary["per_type"][0]["rows_before"], 3)
        finally:
            harness.cleanup()

    def test_monitor_persists_state_asset(self) -> None:
        harness = build_test_harness()
        try:
            self._seed_assets(harness, "runtime_bridge_state", [100.0, 1.0])
            monitor = MemoryAssetsRetentionMonitor(
                memory_assets=harness.container.memory_assets,
                config=MemoryRetentionConfig(
                    enabled=True, policies={"runtime_bridge_state": "48h"}
                ),
            )
            monitor.scan_once()
            state_asset = harness.container.memory_assets.get_asset(
                "memory_retention_state"
            )
            self.assertIsNotNone(state_asset)
            payload = state_asset["payload"]
            self.assertIn("scanned_at_utc", payload)
            self.assertIn("per_type", payload)
            self.assertEqual(payload["total_deleted"], 1)
        finally:
            harness.cleanup()

    def test_backlog_too_large_skips_inline_delete(self) -> None:
        """When live count is way above max_deletes_per_type_per_scan, the
        monitor must skip the DELETE so a multi-month bulk doesn't lock the
        WAL writer for minutes. Operator runs the offline cleanup script."""
        harness = build_test_harness()
        try:
            # cap=10 → backlog threshold = 4*10 = 40. Seed 50 old rows.
            self._seed_assets(harness, "runtime_bridge_state", [100.0] * 50)
            monitor = MemoryAssetsRetentionMonitor(
                memory_assets=harness.container.memory_assets,
                config=MemoryRetentionConfig(
                    enabled=True,
                    policies={"runtime_bridge_state": "48h"},
                    max_deletes_per_type_per_scan=10,
                ),
            )
            summary = monitor.scan_once()
            # Nothing deleted; entry carries the backlog note.
            self.assertEqual(summary["total_deleted"], 0)
            note = summary["per_type"][0].get("note")
            self.assertEqual(note, "backlog_too_large_skip_let_offline_script_run")
            # All 50 rows still present.
            self.assertEqual(
                harness.container.memory_assets.count_assets_by_type(
                    asset_type="runtime_bridge_state"
                ),
                50,
            )
        finally:
            harness.cleanup()

    def test_per_type_ttls_are_independent(self) -> None:
        """Different types get different TTLs in one scan."""
        harness = build_test_harness()
        try:
            # bridge: 100h, 30h, 1h (TTL 48h → delete 1)
            # leases: 50d old, 10d old (TTL 30d → delete 1)
            self._seed_assets(harness, "runtime_bridge_state", [100.0, 30.0, 1.0])
            self._seed_assets(harness, "agent_runtime_lease", [50 * 24.0, 10 * 24.0])
            monitor = MemoryAssetsRetentionMonitor(
                memory_assets=harness.container.memory_assets,
                config=MemoryRetentionConfig(
                    enabled=True,
                    policies={
                        "runtime_bridge_state": "48h",
                        "agent_runtime_lease": "30d",
                    },
                ),
            )
            summary = monitor.scan_once()
            self.assertEqual(summary["total_deleted"], 2)
            by_type = {e["asset_type"]: e["deleted"] for e in summary["per_type"]}
            self.assertEqual(by_type["runtime_bridge_state"], 1)
            self.assertEqual(by_type["agent_runtime_lease"], 1)
        finally:
            harness.cleanup()

    def test_disabled_monitor_does_not_start_thread(self) -> None:
        harness = build_test_harness()
        try:
            monitor = MemoryAssetsRetentionMonitor(
                memory_assets=harness.container.memory_assets,
                config=MemoryRetentionConfig(enabled=False, policies={}),
            )
            monitor.start()
            self.assertIsNone(monitor._thread)
            monitor.stop()
        finally:
            harness.cleanup()

    def test_monitor_constructor_validates_ttl_specs_eagerly(self) -> None:
        """A typo in policy config should fail at startup, not 1 hour later
        in the background thread where the user can't see it."""
        harness = build_test_harness()
        try:
            with self.assertRaises(ValueError):
                MemoryAssetsRetentionMonitor(
                    memory_assets=harness.container.memory_assets,
                    config=MemoryRetentionConfig(
                        enabled=True,
                        policies={"runtime_bridge_state": "48 hours"},  # typo
                    ),
                )
        finally:
            harness.cleanup()


class PortfolioSnapshotsTableRetentionTests(unittest.TestCase):
    """Phase 3 follow-up (audit 2026-05-07): the dedicated portfolio_snapshots
    TABLE — separate from `assets.portfolio_snapshot` rows — was dual-written
    by bridge with no retention. These tests cover the new
    portfolio_snapshots_ttl path on MemoryAssetsRetentionMonitor."""

    def _seed_portfolio_snapshots(self, harness, ages_hours: list[float]) -> None:
        """Insert N portfolio_snapshots TABLE rows with controlled created_at."""
        now = datetime.now(UTC)
        for i, age_h in enumerate(ages_hours):
            harness.container.memory_assets.save_portfolio(
                trace_id=f"trace_seed_{i}",
                payload={"total_equity_usd": str(1000 + i), "seq": i},
            )
        with harness.container.memory_assets.repository.database.connect() as conn:
            rows = list(conn.execute(
                "SELECT snapshot_id FROM portfolio_snapshots ORDER BY created_at ASC"
            ))
            for row, age_h in zip(rows, ages_hours):
                target_ts = (now - timedelta(hours=age_h)).isoformat()
                conn.execute(
                    "UPDATE portfolio_snapshots SET created_at = ? WHERE snapshot_id = ?",
                    (target_ts, row[0]),
                )

    def test_portfolio_snapshots_pruned_by_ttl(self) -> None:
        harness = build_test_harness()
        try:
            self._seed_portfolio_snapshots(harness, [100 * 24.0, 70 * 24.0, 30 * 24.0, 1.0])
            monitor = MemoryAssetsRetentionMonitor(
                memory_assets=harness.container.memory_assets,
                config=MemoryRetentionConfig(
                    enabled=True, policies={}, portfolio_snapshots_ttl="60d"
                ),
            )
            summary = monitor.scan_once()
            self.assertIn("portfolio_snapshots_table", summary)
            entry = summary["portfolio_snapshots_table"]
            self.assertEqual(entry["target"], "portfolio_snapshots_table")
            self.assertEqual(entry["rows_before"], 4)
            self.assertEqual(entry["deleted"], 2)
            self.assertEqual(entry["rows_after"], 2)
            self.assertEqual(
                harness.container.memory_assets.count_portfolio_snapshots(), 2
            )
        finally:
            harness.cleanup()

    def test_portfolio_snapshots_disabled_by_zero_ttl(self) -> None:
        harness = build_test_harness()
        try:
            self._seed_portfolio_snapshots(harness, [100 * 24.0, 1.0])
            monitor = MemoryAssetsRetentionMonitor(
                memory_assets=harness.container.memory_assets,
                config=MemoryRetentionConfig(
                    enabled=True, policies={}, portfolio_snapshots_ttl=0
                ),
            )
            summary = monitor.scan_once()
            self.assertNotIn("portfolio_snapshots_table", summary)
            self.assertEqual(
                harness.container.memory_assets.count_portfolio_snapshots(), 2
            )
        finally:
            harness.cleanup()

    def test_portfolio_snapshots_within_ttl_kept(self) -> None:
        harness = build_test_harness()
        try:
            self._seed_portfolio_snapshots(harness, [50 * 24.0, 30 * 24.0, 1.0])
            monitor = MemoryAssetsRetentionMonitor(
                memory_assets=harness.container.memory_assets,
                config=MemoryRetentionConfig(
                    enabled=True, policies={}, portfolio_snapshots_ttl="60d"
                ),
            )
            summary = monitor.scan_once()
            entry = summary["portfolio_snapshots_table"]
            self.assertEqual(entry["deleted"], 0)
            self.assertEqual(entry["rows_after"], 3)
        finally:
            harness.cleanup()

    def test_portfolio_snapshots_backlog_guard(self) -> None:
        """Backlog way over the cap → defer to offline cleanup script."""
        harness = build_test_harness()
        try:
            self._seed_portfolio_snapshots(harness, [100 * 24.0] * 50)
            monitor = MemoryAssetsRetentionMonitor(
                memory_assets=harness.container.memory_assets,
                config=MemoryRetentionConfig(
                    enabled=True,
                    policies={},
                    portfolio_snapshots_ttl="60d",
                    max_deletes_per_type_per_scan=10,  # backlog threshold = 40
                ),
            )
            summary = monitor.scan_once()
            entry = summary["portfolio_snapshots_table"]
            self.assertEqual(entry["deleted"], 0)
            self.assertEqual(
                entry.get("note"), "backlog_too_large_skip_let_offline_script_run"
            )
            self.assertEqual(
                harness.container.memory_assets.count_portfolio_snapshots(), 50
            )
        finally:
            harness.cleanup()

    def test_portfolio_snapshots_pass_independent_of_assets_pass(self) -> None:
        """Both passes can run in one scan — assets policies + portfolio
        snapshots table — without interfering."""
        harness = build_test_harness()
        try:
            self._seed_portfolio_snapshots(harness, [100 * 24.0, 30 * 24.0, 1.0])
            now = datetime.now(UTC)
            for i, age_h in enumerate([100.0, 30.0, 1.0]):
                harness.container.memory_assets.save_asset(
                    asset_type="runtime_bridge_state",
                    asset_id=f"bridge_{i}",
                    payload={"i": i},
                    actor_role="system",
                )
                with harness.container.memory_assets.repository.database.connect() as conn:
                    target_ts = (now - timedelta(hours=age_h)).isoformat()
                    conn.execute(
                        "UPDATE assets SET created_at = ? WHERE asset_id = ?",
                        (target_ts, f"bridge_{i}"),
                    )
            monitor = MemoryAssetsRetentionMonitor(
                memory_assets=harness.container.memory_assets,
                config=MemoryRetentionConfig(
                    enabled=True,
                    policies={"runtime_bridge_state": "48h"},
                    portfolio_snapshots_ttl="60d",
                ),
            )
            summary = monitor.scan_once()
            assets_entry = next(
                e for e in summary["per_type"] if e["asset_type"] == "runtime_bridge_state"
            )
            self.assertEqual(assets_entry["deleted"], 1)
            self.assertEqual(summary["portfolio_snapshots_table"]["deleted"], 1)
            self.assertEqual(summary["total_deleted"], 2)
        finally:
            harness.cleanup()

    def test_portfolio_snapshots_ttl_typo_fails_eagerly(self) -> None:
        harness = build_test_harness()
        try:
            with self.assertRaises(ValueError):
                MemoryAssetsRetentionMonitor(
                    memory_assets=harness.container.memory_assets,
                    config=MemoryRetentionConfig(
                        enabled=True,
                        policies={},
                        portfolio_snapshots_ttl="60 days",  # typo
                    ),
                )
        finally:
            harness.cleanup()


if __name__ == "__main__":
    unittest.main()
