"""Event-driven PM wake monitor: price-conditioned rechecks.

PM authors `price_rechecks: [{subscription_id, metric, operator, threshold,
scope, reason}, ...]` on its strategy submission. Each subscription is a
one-shot promise: "wake me when this metric crosses this threshold". This
monitor evaluates them every ~30s against `runtime_bridge_state.context`
and dispatches PM via session message + `pm_trigger_event` when any
subscription's condition is satisfied.

Why event-driven matters: today PM's only wake paths are time-based
(scheduled_recheck) or pushed by other agents (RT/MEA/risk_brake). PM
writes prose `flip_triggers` like "Brent>108 → flip to short" but
nothing watches for it — RT does NOT auto-execute flip_triggers (verified
2026-04-27). Without this monitor, PM's pre-authored conditional plans
never become reality unless PM independently wakes (max_silence_since)
and notices on her own.

Per-subscription dedup: each (strategy_id, subscription_id) fires at most
once. Old subscriptions are auto-orphaned when PM submits a new strategy
(latest_strategy filter); their dedup keys persist in state to defend
against pathological re-fires across restarts.

Whitelist of allowed metric paths (defense in depth, since the schema is
narrow but submit could have legacy rows):
  - market.market.<COIN>.mark_price
  - market.market.<COIN>.index_price
  - macro_prices.<symbol>.price
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event, Thread
from typing import Any

from ...shared.infra import EventBus
from ...shared.utils import new_id
from ..memory_assets.service import MemoryAssetsService
from .agent_dispatch import AgentDispatcher, AgentDispatchConfig
from .pm_trigger import record_pm_trigger_event


_STATE_ASSET_ID = "price_recheck_state_monitor"

# Whitelist regex set: anchors against full metric path.
_METRIC_WHITELIST = (
    re.compile(r"^market\.market\.[A-Z0-9_-]+\.mark_price$"),
    re.compile(r"^market\.market\.[A-Z0-9_-]+\.index_price$"),
    re.compile(r"^macro_prices\.[a-z0-9_]+\.price$"),
)


@dataclass(frozen=True)
class PriceRecheckConfig:
    enabled: bool = False
    scan_interval_seconds: int = 30
    global_cooldown_seconds: int = 60
    pm_session_key: str = "agent:pm:main"
    cron_subprocess_timeout_seconds: int = 15
    openclaw_bin: str = "openclaw"


class PriceRecheckMonitor:
    def __init__(
        self,
        *,
        memory_assets: MemoryAssetsService,
        event_bus: EventBus | None = None,
        config: PriceRecheckConfig | None = None,
        agent_dispatcher: AgentDispatcher | None = None,
    ) -> None:
        self.memory_assets = memory_assets
        self.event_bus = event_bus
        self.config = config or PriceRecheckConfig()
        self.agent_dispatcher = agent_dispatcher or AgentDispatcher(
            config=AgentDispatchConfig(
                openclaw_bin=self.config.openclaw_bin,
                subprocess_timeout_seconds=self.config.cron_subprocess_timeout_seconds,
            ),
        )
        self._stop = Event()
        self._thread: Thread | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        if not self.config.enabled or self._thread is not None:
            return
        self._thread = Thread(
            target=self._loop, name="workflow-orchestrator-price-recheck", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.scan_once()
            except Exception:  # noqa: BLE001
                pass
            if self._stop.wait(max(int(self.config.scan_interval_seconds), 5)):
                break

    # ------------------------------------------------------------------
    # Scan
    # ------------------------------------------------------------------
    def scan_once(self, *, now: datetime | None = None) -> dict[str, Any]:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        latest_strategy = self.memory_assets.get_latest_strategy() or {}
        strategy_payload = dict(latest_strategy.get("payload") or latest_strategy or {})
        strategy_id = str(strategy_payload.get("strategy_id") or "")
        revision_number = strategy_payload.get("revision_number")
        subscriptions = list(strategy_payload.get("price_rechecks") or [])
        state = self._load_state()
        last_global_dispatch = self._parse_iso(state.get("last_global_dispatch_utc"))
        if last_global_dispatch is not None and (current - last_global_dispatch).total_seconds() < float(
            self.config.global_cooldown_seconds
        ):
            return self._scan_summary(state, current, "global_cooldown_active", 0)
        if not strategy_id or not subscriptions:
            self._save_state(state, current)
            return self._scan_summary(state, current, "no_subscriptions", 0)

        bridge_asset = self.memory_assets.latest_runtime_bridge_state_asset()
        bridge_payload = dict((bridge_asset or {}).get("payload") or {})
        context = dict(bridge_payload.get("context") or {})

        completed = set(state.get("fired_keys") or [])
        fired_now: list[dict[str, Any]] = []
        for sub in subscriptions:
            if not isinstance(sub, dict):
                continue
            sub_id = str(sub.get("subscription_id") or "").strip()
            metric_path = str(sub.get("metric") or "").strip()
            operator = str(sub.get("operator") or "").strip()
            try:
                threshold = float(sub.get("threshold"))
            except (TypeError, ValueError):
                continue
            if not sub_id or not self._metric_allowed(metric_path):
                continue
            key = self._fired_key(strategy_id, sub_id)
            if key in completed:
                continue
            observed = self._resolve_metric(context, metric_path)
            if observed is None:
                continue
            if not self._compare(observed, operator, threshold):
                continue
            fired_now.append(
                {
                    "key": key,
                    "subscription": dict(sub),
                    "observed_value": observed,
                    "strategy_id": strategy_id,
                    "revision_number": revision_number,
                }
            )

        if not fired_now:
            self._save_state(state, current)
            return self._scan_summary(state, current, "no_match", 0)

        # Dispatch ONCE per scan, packaging all fired subscriptions into a
        # single owner wake. global_cooldown then prevents subsequent scans
        # from re-firing within the cooldown window.
        dispatched = self._dispatch_combined(
            current=current,
            strategy_id=strategy_id,
            revision_number=revision_number,
            fired=fired_now,
        )
        for f in fired_now:
            completed.add(f["key"])
        state["fired_keys"] = sorted(completed)[-128:]  # cap history
        if dispatched:
            state["last_global_dispatch_utc"] = current.isoformat()
        self._save_state(state, current)
        return self._scan_summary(
            state, current, "dispatched" if dispatched else "dispatch_failed", len(fired_now)
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _metric_allowed(metric: str) -> bool:
        return any(p.match(metric) for p in _METRIC_WHITELIST)

    @staticmethod
    def _resolve_metric(context: dict[str, Any], metric: str) -> float | None:
        cursor: Any = context
        for key in metric.split("."):
            if isinstance(cursor, dict):
                cursor = cursor.get(key)
            else:
                return None
            if cursor is None:
                return None
        try:
            return float(cursor)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _compare(observed: float, operator: str, threshold: float) -> bool:
        if operator == ">=":
            return observed >= threshold
        if operator == "<=":
            return observed <= threshold
        if operator == ">":
            return observed > threshold
        if operator == "<":
            return observed < threshold
        return False

    @staticmethod
    def _fired_key(strategy_id: str, subscription_id: str) -> str:
        return f"{strategy_id}|{subscription_id}"

    def _dispatch_combined(
        self,
        *,
        current: datetime,
        strategy_id: str,
        revision_number: Any,
        fired: list[dict[str, Any]],
    ) -> bool:
        # First fired wins as the "primary" condition for the wake message;
        # all others are listed in the payload for PM context.
        primary = fired[0]
        primary_sub = primary["subscription"]
        message_lines = [
            f"[price-recheck] PM 价格订阅触发 — strategy_id={strategy_id} rev={revision_number}",
            "",
            f"主触发: subscription_id={primary_sub.get('subscription_id')}",
            f"  metric={primary_sub.get('metric')} {primary_sub.get('operator')} threshold={primary_sub.get('threshold')}",
            f"  observed={primary['observed_value']}",
            f"  reason={primary_sub.get('reason')}",
        ]
        if len(fired) > 1:
            message_lines.append("")
            message_lines.append(f"附加 {len(fired) - 1} 条同时触发：")
            for f in fired[1:]:
                sub = f["subscription"]
                message_lines.append(
                    f"  - {sub.get('subscription_id')}: {sub.get('metric')} {sub.get('operator')} {sub.get('threshold')} (obs={f['observed_value']})"
                )
        message_lines.append("")
        message_lines.append(
            "请评估是否切换到对应预案 / 撤回原 mandate / 调整 band。提交新 strategy revision 时记得更新或清空已触发的 price_rechecks。"
        )
        message = "\n".join(message_lines)
        try:
            result = self.agent_dispatcher.send_to_session(
                agent="pm",
                session_key=self.config.pm_session_key,
                message=message,
            )
            dispatched = bool(getattr(result, "ok", False))
        except Exception:  # noqa: BLE001
            dispatched = False

        # Always record pm_trigger_event so PM's runtime_pack picks it up
        # next pull (even if dispatch sub failed, the wake is logged).
        record_pm_trigger_event(
            memory_assets=self.memory_assets,
            event_bus=self.event_bus,
            trace_id=new_id("trace"),
            payload={
                "event_id": new_id("pm_trigger"),
                "detected_at_utc": current.isoformat(),
                "trigger_type": "price_recheck",
                "trigger_category": "workflow",
                "reason": "price_recheck",
                "severity": "normal",
                "wake_source": "workflow_orchestrator",
                "claimable": dispatched,
                "strategy_id": strategy_id,
                "revision_number": revision_number,
                "scope": str(primary_sub.get("scope") or "portfolio"),
                "fired_subscriptions": [
                    {
                        "subscription_id": str(f["subscription"].get("subscription_id") or ""),
                        "metric": str(f["subscription"].get("metric") or ""),
                        "operator": str(f["subscription"].get("operator") or ""),
                        "threshold": f["subscription"].get("threshold"),
                        "observed_value": f["observed_value"],
                        "reason": str(f["subscription"].get("reason") or ""),
                    }
                    for f in fired
                ],
                "dispatched": dispatched,
            },
            metadata={"trigger_type": "price_recheck"},
        )
        return dispatched

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------
    def _load_state(self) -> dict[str, Any]:
        asset = self.memory_assets.get_asset(_STATE_ASSET_ID)
        return dict((asset or {}).get("payload") or {})

    def _save_state(self, state: dict[str, Any], now: datetime) -> None:
        state["last_scanned_at_utc"] = now.isoformat()
        self.memory_assets.save_asset(
            asset_type="price_recheck_state_monitor",
            asset_id=_STATE_ASSET_ID,
            payload=state,
            actor_role="system",
            group_key=_STATE_ASSET_ID,
        )

    @staticmethod
    def _parse_iso(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return ts.astimezone(UTC)

    @staticmethod
    def _scan_summary(
        state: dict[str, Any], current: datetime, status: str, fire_count: int
    ) -> dict[str, Any]:
        return {
            "scanned_at_utc": current.isoformat(),
            "status": status,
            "fired_count": fire_count,
            "fired_keys_total": len(state.get("fired_keys") or []),
        }
