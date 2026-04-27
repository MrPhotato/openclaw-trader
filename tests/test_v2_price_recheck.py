from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from openclaw_trader.modules.memory_assets.models import PriceRecheck, StrategyAsset
from openclaw_trader.modules.workflow_orchestrator.price_recheck import (
    PriceRecheckConfig,
    PriceRecheckMonitor,
    _STATE_ASSET_ID,
)

from .helpers_v2 import build_test_harness


class _CapturingDispatcher:
    """In-process AgentDispatcher stub: captures send_to_session calls so a
    test can assert what wake message PM would have received without
    spawning a real openclaw subprocess.
    """

    def __init__(self, *, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list[dict] = []

    def send_to_session(self, *, agent: str, session_key: str, message: str, **_kw):
        self.calls.append({"agent": agent, "session_key": session_key, "message": message})

        class _R:
            ok = self.ok

        return _R()


def _seed_strategy(memory, *, strategy_id: str = "strategy_xyz", revision_number: int = 100,
                   price_rechecks: list[dict] | None = None) -> dict:
    """Materialise a strategy asset with an optional price_rechecks array."""
    payload = {
        "strategy_id": strategy_id,
        "strategy_day_utc": "2026-04-27",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "trigger_type": "manual",
        "supersedes_strategy_id": None,
        "revision_number": revision_number,
        "portfolio_mode": "defensive",
        "target_gross_exposure_band_pct": [0.0, 10.0],
        "portfolio_thesis": [
            {"statement": "btc bullish", "evidence_type": "regime", "evidence_sources": ["chief"]}
        ],
        "portfolio_invalidation": "x",
        "flip_triggers": "Brent>108 → short",
        "change_summary": {
            "headline": "h",
            "evidence_breakdown": {"price_action_pct": 25, "quant_forecast_pct": 25, "narrative_pct": 25, "regime_pct": 25},
        },
        "targets": [
            {
                "symbol": "BTC", "state": "active", "direction": "long",
                "target_exposure_band_pct": [0.0, 10.0], "rt_discretion_band_pct": 10.0, "priority": 1,
            },
            {
                "symbol": "ETH", "state": "watch", "direction": "flat",
                "target_exposure_band_pct": [0.0, 0.0], "rt_discretion_band_pct": 0.0, "priority": 2,
            },
        ],
        "scheduled_rechecks": [],
        "price_rechecks": price_rechecks or [],
        "internal_reasoning_only": False,
    }
    canonical = StrategyAsset.model_validate(payload).model_dump(mode="json")
    memory.save_asset(
        asset_type="strategy", payload=canonical, actor_role="pm",
        group_key=str(canonical["strategy_day_utc"]),
    )
    memory.save_strategy(str(canonical["strategy_id"]), "trace-test", canonical)
    return canonical


def _seed_bridge(memory, *, btc_mark: float | None = None, brent_price: float | None = None) -> None:
    context: dict = {"market": {"market": {}}, "macro_prices": {}}
    if btc_mark is not None:
        context["market"]["market"]["BTC"] = {"mark_price": btc_mark}
    if brent_price is not None:
        context["macro_prices"]["brent"] = {"price": brent_price}
    memory.save_asset(
        asset_type="runtime_bridge_state",
        payload={"context": context, "refreshed_at_utc": datetime.now(UTC).isoformat()},
        actor_role="system",
    )


class PriceRecheckSchemaTests(unittest.TestCase):
    def test_strategy_asset_default_empty_array(self) -> None:
        """Back-compat: legacy strategies without `price_rechecks` validate."""
        payload = {
            "strategy_id": "x", "strategy_day_utc": "2026-04-27",
            "generated_at_utc": datetime.now(UTC).isoformat(), "trigger_type": "manual",
            "revision_number": 1, "portfolio_mode": "flat",
            "target_gross_exposure_band_pct": [0, 0],
            "portfolio_thesis": [{"statement": "s", "evidence_type": "regime", "evidence_sources": ["x"]}],
            "portfolio_invalidation": "x", "flip_triggers": "x",
            "change_summary": {"headline": "h", "evidence_breakdown": {"price_action_pct": 0, "quant_forecast_pct": 0, "narrative_pct": 0, "regime_pct": 100}},
            "targets": [
                {"symbol": "BTC", "state": "watch", "direction": "flat", "target_exposure_band_pct": [0, 0], "rt_discretion_band_pct": 0, "priority": 1},
                {"symbol": "ETH", "state": "watch", "direction": "flat", "target_exposure_band_pct": [0, 0], "rt_discretion_band_pct": 0, "priority": 2},
            ],
        }
        s = StrategyAsset.model_validate(payload)
        self.assertEqual(s.price_rechecks, [])

    def test_price_recheck_operator_enum(self) -> None:
        for op in (">=", "<=", ">", "<"):
            PriceRecheck(
                subscription_id="s", metric="market.market.BTC.mark_price",
                operator=op, threshold=1.0, scope="portfolio", reason="r",
            )
        with self.assertRaises(Exception):
            PriceRecheck(
                subscription_id="s", metric="market.market.BTC.mark_price",
                operator="==", threshold=1.0, scope="portfolio", reason="r",
            )


class PriceRecheckMonitorTests(unittest.TestCase):
    def _make_monitor(self, harness, *, dispatcher=None, cooldown=60) -> tuple[PriceRecheckMonitor, _CapturingDispatcher]:
        d = dispatcher or _CapturingDispatcher()
        m = PriceRecheckMonitor(
            memory_assets=harness.container.memory_assets,
            event_bus=harness.event_bus,
            config=PriceRecheckConfig(enabled=True, global_cooldown_seconds=cooldown),
            agent_dispatcher=d,
        )
        return m, d

    def test_no_strategy_no_subscriptions_short_circuits(self) -> None:
        h = build_test_harness()
        try:
            m, d = self._make_monitor(h)
            result = m.scan_once()
            self.assertEqual(result["status"], "no_subscriptions")
            self.assertEqual(d.calls, [])
        finally:
            h.cleanup()

    def test_fires_when_btc_mark_breaches_upward(self) -> None:
        h = build_test_harness()
        try:
            memory = h.container.memory_assets
            _seed_strategy(memory, price_rechecks=[
                {"subscription_id": "btc_breakout", "metric": "market.market.BTC.mark_price",
                 "operator": ">=", "threshold": 80000.0, "scope": "portfolio",
                 "reason": "evaluate plan A"},
            ])
            _seed_bridge(memory, btc_mark=80125.5)
            m, d = self._make_monitor(h)
            result = m.scan_once()
            self.assertEqual(result["status"], "dispatched")
            self.assertEqual(result["fired_count"], 1)
            self.assertEqual(len(d.calls), 1)
            self.assertEqual(d.calls[0]["agent"], "pm")
            self.assertIn("btc_breakout", d.calls[0]["message"])
            self.assertIn("80125.5", d.calls[0]["message"])
            # pm_trigger_event recorded
            events = memory.recent_assets(asset_type="pm_trigger_event", limit=5)
            self.assertTrue(any(
                (e.get("payload") or {}).get("trigger_type") == "price_recheck"
                for e in events
            ))
        finally:
            h.cleanup()

    def test_does_not_fire_when_threshold_not_met(self) -> None:
        h = build_test_harness()
        try:
            memory = h.container.memory_assets
            _seed_strategy(memory, price_rechecks=[
                {"subscription_id": "x", "metric": "market.market.BTC.mark_price",
                 "operator": ">=", "threshold": 80000, "scope": "portfolio", "reason": "r"},
            ])
            _seed_bridge(memory, btc_mark=78000)
            m, d = self._make_monitor(h)
            result = m.scan_once()
            self.assertEqual(result["status"], "no_match")
            self.assertEqual(d.calls, [])
        finally:
            h.cleanup()

    def test_dedup_within_same_strategy(self) -> None:
        """Same (strategy_id, subscription_id) must not fire twice. Use 0
        cooldown so the second scan is not gated by global cooldown."""
        h = build_test_harness()
        try:
            memory = h.container.memory_assets
            _seed_strategy(memory, price_rechecks=[
                {"subscription_id": "x", "metric": "market.market.BTC.mark_price",
                 "operator": ">=", "threshold": 80000, "scope": "portfolio", "reason": "r"},
            ])
            _seed_bridge(memory, btc_mark=80100)
            m, d = self._make_monitor(h, cooldown=0)
            r1 = m.scan_once()
            self.assertEqual(r1["status"], "dispatched")
            r2 = m.scan_once()
            self.assertEqual(r2["status"], "no_match")
            self.assertEqual(len(d.calls), 1)
        finally:
            h.cleanup()

    def test_global_cooldown_prevents_back_to_back_fires(self) -> None:
        h = build_test_harness()
        try:
            memory = h.container.memory_assets
            _seed_strategy(memory, price_rechecks=[
                {"subscription_id": "a", "metric": "market.market.BTC.mark_price",
                 "operator": ">=", "threshold": 80000, "scope": "portfolio", "reason": "r"},
            ])
            _seed_bridge(memory, btc_mark=80100)
            m, d = self._make_monitor(h, cooldown=300)
            now = datetime.now(UTC)
            m.scan_once(now=now)
            self.assertEqual(len(d.calls), 1)
            # Even if a new subscription on a new strategy id fires, cooldown wins
            _seed_strategy(memory, strategy_id="strategy_other", revision_number=2,
                           price_rechecks=[{"subscription_id": "b", "metric": "market.market.BTC.mark_price",
                                             "operator": ">=", "threshold": 80000, "scope": "portfolio", "reason": "r"}])
            _seed_bridge(memory, btc_mark=80200)
            r = m.scan_once(now=now + timedelta(seconds=10))
            self.assertEqual(r["status"], "global_cooldown_active")
            # After cooldown elapses, fires again
            r2 = m.scan_once(now=now + timedelta(seconds=400))
            self.assertEqual(r2["status"], "dispatched")
        finally:
            h.cleanup()

    def test_reject_metric_outside_whitelist(self) -> None:
        """A subscription whose metric is not in the allow-list (e.g. anything
        outside market.market.<COIN>.{mark,index}_price + macro_prices.<sym>.price)
        must be silently dropped — no fire even if the path resolves and beats the threshold.
        """
        h = build_test_harness()
        try:
            memory = h.container.memory_assets
            _seed_strategy(memory, price_rechecks=[
                {"subscription_id": "evil", "metric": "forecasts.BTC.diagnostics.something",
                 "operator": ">=", "threshold": 0, "scope": "portfolio", "reason": "r"},
            ])
            memory.save_asset(
                asset_type="runtime_bridge_state",
                payload={"context": {"forecasts": {"BTC": {"diagnostics": {"something": 999}}}}},
                actor_role="system",
            )
            m, d = self._make_monitor(h, cooldown=0)
            result = m.scan_once()
            self.assertEqual(result["status"], "no_match")
            self.assertEqual(d.calls, [])
        finally:
            h.cleanup()

    def test_brent_macro_price_breach(self) -> None:
        h = build_test_harness()
        try:
            memory = h.container.memory_assets
            _seed_strategy(memory, price_rechecks=[
                {"subscription_id": "brent_breach", "metric": "macro_prices.brent.price",
                 "operator": ">=", "threshold": 108, "scope": "portfolio", "reason": "plan A activate"},
            ])
            _seed_bridge(memory, brent_price=108.42)
            m, d = self._make_monitor(h)
            result = m.scan_once()
            self.assertEqual(result["status"], "dispatched")
            self.assertIn("brent_breach", d.calls[0]["message"])
            self.assertIn("108.42", d.calls[0]["message"])
        finally:
            h.cleanup()

    def test_combined_dispatch_when_multiple_subscriptions_satisfied(self) -> None:
        """Two subscriptions cleared simultaneously → ONE wake message with
        both listed (per design: don't flood PM with parallel subprocess
        spawns; first scan packages all satisfied subs).
        """
        h = build_test_harness()
        try:
            memory = h.container.memory_assets
            _seed_strategy(memory, price_rechecks=[
                {"subscription_id": "btc_up", "metric": "market.market.BTC.mark_price",
                 "operator": ">=", "threshold": 80000, "scope": "portfolio", "reason": "btc"},
                {"subscription_id": "brent_up", "metric": "macro_prices.brent.price",
                 "operator": ">=", "threshold": 108, "scope": "portfolio", "reason": "brent"},
            ])
            _seed_bridge(memory, btc_mark=81000, brent_price=109)
            m, d = self._make_monitor(h)
            result = m.scan_once()
            self.assertEqual(result["status"], "dispatched")
            self.assertEqual(result["fired_count"], 2)
            self.assertEqual(len(d.calls), 1)
            msg = d.calls[0]["message"]
            self.assertIn("btc_up", msg)
            self.assertIn("brent_up", msg)
        finally:
            h.cleanup()

    def test_state_persists_fired_keys_across_restart(self) -> None:
        """Recreating the monitor (= process restart) must NOT re-fire keys
        that were already dispatched; state asset is the source of truth.
        """
        h = build_test_harness()
        try:
            memory = h.container.memory_assets
            _seed_strategy(memory, price_rechecks=[
                {"subscription_id": "x", "metric": "market.market.BTC.mark_price",
                 "operator": ">=", "threshold": 80000, "scope": "portfolio", "reason": "r"},
            ])
            _seed_bridge(memory, btc_mark=80100)
            m1, d1 = self._make_monitor(h, cooldown=0)
            m1.scan_once()
            self.assertEqual(len(d1.calls), 1)
            # Verify state contains the key
            state = memory.get_asset(_STATE_ASSET_ID)
            self.assertIsNotNone(state)
            self.assertIn("strategy_xyz|x", (state.get("payload") or {}).get("fired_keys") or [])
            # New monitor instance, fresh dispatcher, same state asset
            m2, d2 = self._make_monitor(h, cooldown=0)
            m2.scan_once()
            self.assertEqual(d2.calls, [], "Restart must not re-fire previously dispatched keys")
        finally:
            h.cleanup()

    def test_missing_bridge_state_does_not_crash(self) -> None:
        h = build_test_harness()
        try:
            memory = h.container.memory_assets
            _seed_strategy(memory, price_rechecks=[
                {"subscription_id": "x", "metric": "market.market.BTC.mark_price",
                 "operator": ">=", "threshold": 80000, "scope": "portfolio", "reason": "r"},
            ])
            # Note: no bridge state seeded
            m, d = self._make_monitor(h)
            result = m.scan_once()
            self.assertEqual(result["status"], "no_match")
            self.assertEqual(d.calls, [])
        finally:
            h.cleanup()


if __name__ == "__main__":
    unittest.main()
