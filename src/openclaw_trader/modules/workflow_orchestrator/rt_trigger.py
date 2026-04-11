from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from threading import Event, Thread
from typing import Any

from ...shared.infra import EventBus
from ...shared.protocols import EventFactory
from ...shared.utils import new_id
from ..memory_assets.service import MemoryAssetsService
from ..trade_gateway.market_data.models import DataIngestBundle, MarketContextNormalized
from ..trade_gateway.market_data.service import DataIngestService
from .events import EVENT_RT_TRIGGER_DETECTED, MODULE_NAME


DEFAULT_RT_JOB_ID = "ccbf7286-dba4-4d57-bebe-932340374492"


@dataclass(frozen=True)
class RTTriggerConfig:
    enabled: bool = False
    rt_job_id: str = DEFAULT_RT_JOB_ID
    scan_interval_seconds: int = 30
    global_cooldown_seconds: int = 300
    key_cooldown_seconds: int = 900
    max_runs_per_hour: int = 4
    position_heartbeat_minutes: int = 60
    flat_heartbeat_minutes: int = 120
    exposure_drift_pct_of_exposure_budget: float = 2.0
    execution_followup_delay_seconds: int = 180
    cron_subprocess_timeout_seconds: int = 15
    max_leverage: float = 5.0
    openclaw_bin: str = "openclaw"


@dataclass(frozen=True)
class CronRunResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None


@dataclass(frozen=True)
class RTTriggerDecision:
    reason: str
    severity: str = "normal"
    coins: tuple[str, ...] = ()
    cooldown_key: str = "global"
    bypass_cooldown: bool = False
    metrics: dict[str, Any] = field(default_factory=dict)
    source_asset_ids: tuple[str, ...] = ()


class OpenClawCronRunner:
    def __init__(self, *, openclaw_bin: str = "openclaw", timeout_seconds: int = 15) -> None:
        self.openclaw_bin = openclaw_bin
        self.timeout_seconds = timeout_seconds

    def is_running(self, *, job_id: str) -> bool:
        tasks_payload = self._run_json(
            [self.openclaw_bin, "tasks", "--json", "list", "--runtime", "cron", "--status", "running"]
        )
        if self._tasks_include_running_job(tasks_payload, job_id=job_id):
            return True

        cron_payload = self._run_json([self.openclaw_bin, "cron", "list", "--all", "--json"])
        if self._cron_list_has_running_job(cron_payload, job_id=job_id):
            return True

        cron_payload = self._run_json([self.openclaw_bin, "cron", "list", "--json"])
        return self._cron_list_has_running_job(cron_payload, job_id=job_id)

    def _run_json(self, command: list[str]) -> Any:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except Exception:
            return None
        if completed.returncode != 0:
            return None
        return self._load_json_from_completed(completed)

    @staticmethod
    def _load_json_from_completed(completed: subprocess.CompletedProcess[str]) -> Any:
        for text in (completed.stdout, completed.stderr):
            if not text:
                continue
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                continue
        return None

    @staticmethod
    def _tasks_include_running_job(payload: Any, *, job_id: str) -> bool:
        tasks: list[dict[str, Any]] = []
        if isinstance(payload, dict) and isinstance(payload.get("tasks"), list):
            tasks = [item for item in payload["tasks"] if isinstance(item, dict)]
        elif isinstance(payload, list):
            tasks = [item for item in payload if isinstance(item, dict)]
        for task in tasks:
            source_id = str(task.get("sourceId") or task.get("source_id") or task.get("jobId") or task.get("job_id") or "")
            if source_id != job_id:
                continue
            if str(task.get("status") or "").lower() == "running":
                return True
        return False

    @classmethod
    def _cron_list_has_running_job(cls, payload: Any, *, job_id: str) -> bool:
        for job in cls._iter_jobs(payload):
            if str(job.get("id") or job.get("job_id") or job.get("jobId") or "") != job_id:
                continue
            state = job.get("state") if isinstance(job.get("state"), dict) else {}
            running_at = state.get("runningAtMs") or state.get("running_at_ms") or job.get("runningAtMs")
            if running_at:
                return True
        return False

    def run_now(self, *, job_id: str) -> CronRunResult:
        try:
            completed = subprocess.run(
                [self.openclaw_bin, "cron", "run", job_id],
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except Exception as exc:
            return CronRunResult(ok=False, stderr=str(exc))
        return CronRunResult(
            ok=completed.returncode == 0,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            returncode=completed.returncode,
        )

    @staticmethod
    def _iter_jobs(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("jobs", "data", "items"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
            if payload.get("id") or payload.get("job_id") or payload.get("jobId"):
                return [payload]
        return []


class RTTriggerMonitor:
    def __init__(
        self,
        *,
        memory_assets: MemoryAssetsService,
        market_data: DataIngestService,
        event_bus: EventBus | None = None,
        config: RTTriggerConfig | None = None,
        cron_runner: OpenClawCronRunner | None = None,
    ) -> None:
        self.memory_assets = memory_assets
        self.market_data = market_data
        self.event_bus = event_bus
        self.config = config or RTTriggerConfig()
        self.cron_runner = cron_runner or OpenClawCronRunner(
            openclaw_bin=self.config.openclaw_bin,
            timeout_seconds=self.config.cron_subprocess_timeout_seconds,
        )
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if not self.config.enabled or self._thread is not None:
            return
        self._thread = Thread(target=self._loop, name="workflow-orchestrator-rt-trigger", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def scan_once(self, *, now: datetime | None = None) -> dict[str, Any]:
        current = _as_utc(now or datetime.now(UTC))
        state = self._load_state()
        trace_id = new_id("trace")
        market = self.market_data.get_market_overview(trace_id=trace_id)
        decisions = self._detect_triggers(state=state, market=market, now=current)
        event_payload: dict[str, Any] | None = None
        if decisions:
            event_payload = self._handle_decision(decisions[0], state=state, now=current, trace_id=trace_id)
        updated_state = self._updated_state_after_scan(state=state, market=market, now=current)
        if event_payload and event_payload.get("dispatched"):
            updated_state["last_trigger_at_utc"] = current.isoformat()
            updated_state["recent_trigger_times_utc"] = self._recent_trigger_times(state, now=current) + [
                current.isoformat()
            ]
            key = str(event_payload.get("cooldown_key") or "")
            if key:
                by_key = dict(updated_state.get("last_trigger_by_key") or {})
                by_key[key] = current.isoformat()
                updated_state["last_trigger_by_key"] = by_key
        self._save_state(updated_state, trace_id=trace_id)
        return event_payload or {"triggered": False, "scanned_at_utc": current.isoformat()}

    def _loop(self) -> None:
        while not self._stop.wait(max(int(self.config.scan_interval_seconds), 1)):
            try:
                self.scan_once()
            except Exception:
                continue

    def _detect_triggers(
        self,
        *,
        state: dict[str, Any],
        market: DataIngestBundle,
        now: datetime,
    ) -> list[RTTriggerDecision]:
        detectors = (
            self._detect_strategy_update,
            self._detect_high_impact_news,
            self._detect_execution_followup,
            self._detect_market_structure_change,
            self._detect_exposure_drift,
            self._detect_reference_proxy,
            self._detect_heartbeat,
        )
        decisions: list[RTTriggerDecision] = []
        for detector in detectors:
            decision = detector(state=state, market=market, now=now)
            if decision is not None:
                decisions.append(decision)
        return decisions

    def _detect_strategy_update(
        self,
        *,
        state: dict[str, Any],
        market: DataIngestBundle,
        now: datetime,
    ) -> RTTriggerDecision | None:
        latest = self.memory_assets.get_latest_strategy()
        if latest is None:
            return None
        payload = dict(latest.get("payload") or {})
        strategy_key = self._strategy_key(payload)
        if not strategy_key or strategy_key == str(state.get("last_seen_strategy_key") or ""):
            return None
        return RTTriggerDecision(
            reason="pm_strategy_update",
            severity="high",
            cooldown_key="strategy",
            bypass_cooldown=True,
            metrics={"strategy_key": strategy_key, "revision_number": payload.get("revision_number")},
            source_asset_ids=(str(latest.get("asset_id") or ""),),
        )

    def _detect_high_impact_news(
        self,
        *,
        state: dict[str, Any],
        market: DataIngestBundle,
        now: datetime,
    ) -> RTTriggerDecision | None:
        seen = set(state.get("last_seen_event_ids") or [])
        for asset_type in ("macro_event", "news_submission"):
            for asset in self.memory_assets.recent_assets(asset_type=asset_type, limit=20):
                asset_id = str(asset.get("asset_id") or "")
                if not asset_id or asset_id in seen:
                    continue
                severity = self._asset_news_severity(asset)
                if severity not in {"high", "critical"}:
                    continue
                return RTTriggerDecision(
                    reason="mea_high_impact_event",
                    severity=severity,
                    cooldown_key=f"news:{asset_id}",
                    bypass_cooldown=severity == "critical",
                    metrics={"asset_type": asset_type, "impact_level": severity},
                    source_asset_ids=(asset_id,),
                )
        return None

    def _detect_execution_followup(
        self,
        *,
        state: dict[str, Any],
        market: DataIngestBundle,
        now: datetime,
    ) -> RTTriggerDecision | None:
        seen = set(state.get("last_seen_execution_result_ids") or [])
        for asset in self.memory_assets.recent_assets(asset_type="execution_result", actor_role="risk_trader", limit=20):
            asset_id = str(asset.get("asset_id") or "")
            payload = dict(asset.get("payload") or {})
            if not asset_id or asset_id in seen:
                continue
            if not bool(payload.get("success")) or not list(payload.get("fills") or []):
                continue
            executed_at = _parse_datetime(payload.get("executed_at") or asset.get("created_at"))
            if executed_at is not None and now - executed_at < timedelta(seconds=self.config.execution_followup_delay_seconds):
                continue
            coin = str(payload.get("coin") or payload.get("symbol") or "").upper()
            return RTTriggerDecision(
                reason="execution_followup",
                severity="normal",
                coins=tuple([coin] if coin else []),
                cooldown_key=f"execution:{asset_id}",
                metrics={
                    "decision_id": payload.get("decision_id"),
                    "exchange_order_id": payload.get("exchange_order_id"),
                    "fills_count": len(list(payload.get("fills") or [])),
                },
                source_asset_ids=(asset_id,),
            )
        return None

    def _detect_market_structure_change(
        self,
        *,
        state: dict[str, Any],
        market: DataIngestBundle,
        now: datetime,
    ) -> RTTriggerDecision | None:
        eligible = self._eligible_coins(market)
        previous = dict(state.get("last_market_state_by_coin") or {})
        for coin in sorted(eligible):
            context = market.market_context.get(coin)
            snapshot = market.market.get(coin)
            if context is None or snapshot is None:
                continue
            current_state = self._market_state(coin=coin, context=context, mark_price=snapshot.mark_price)
            previous_state = previous.get(coin)
            if not isinstance(previous_state, dict):
                continue
            breakout = str(current_state.get("breakout_state") or "")
            prev_breakout = str(previous_state.get("breakout_state") or "")
            volatility = str(current_state.get("volatility_state") or "")
            prev_volatility = str(previous_state.get("volatility_state") or "")
            crossed = self._crossed_one_hour_level(previous_state, current_state)
            if breakout in {"up_breakout", "down_breakout"} and breakout != prev_breakout:
                return RTTriggerDecision(
                    reason="market_structure_change",
                    severity="normal",
                    coins=(coin,),
                    cooldown_key=f"market_structure:{coin}:{breakout}",
                    metrics={"breakout_state": breakout, "previous_breakout_state": prev_breakout},
                )
            if volatility == "expanding" and volatility != prev_volatility:
                return RTTriggerDecision(
                    reason="market_structure_change",
                    severity="normal",
                    coins=(coin,),
                    cooldown_key=f"market_structure:{coin}:volatility_expanding",
                    metrics={"volatility_state": volatility, "previous_volatility_state": prev_volatility},
                )
            if crossed:
                return RTTriggerDecision(
                    reason="market_structure_change",
                    severity="normal",
                    coins=(coin,),
                    cooldown_key=f"market_structure:{coin}:{crossed}",
                    metrics={"crossed_level": crossed},
                )
        return None

    def _detect_exposure_drift(
        self,
        *,
        state: dict[str, Any],
        market: DataIngestBundle,
        now: datetime,
    ) -> RTTriggerDecision | None:
        latest = self.memory_assets.get_latest_strategy()
        payload = dict((latest or {}).get("payload") or {})
        threshold = float(self.config.exposure_drift_pct_of_exposure_budget)
        gross_band = self._numeric_band(payload.get("target_gross_exposure_band_pct"))
        gross_share = self._gross_exposure_pct(market)
        if gross_band is not None and self._outside_band_by(gross_share, gross_band, threshold):
            return RTTriggerDecision(
                reason="exposure_drift",
                severity="normal",
                cooldown_key="exposure:gross",
                metrics={"gross_exposure_pct_of_exposure_budget": gross_share, "target_band": gross_band},
            )
        position_by_coin = {
            str(position.coin).upper(): float(position.position_share_pct_of_exposure_budget)
            for position in market.portfolio.positions
        }
        for target in list(payload.get("targets") or []):
            if not isinstance(target, dict):
                continue
            coin = str(target.get("symbol") or "").upper()
            band = self._numeric_band(target.get("target_exposure_band_pct"))
            if not coin or band is None:
                continue
            current_share = float(position_by_coin.get(coin, 0.0))
            if self._outside_band_by(current_share, band, threshold):
                return RTTriggerDecision(
                    reason="exposure_drift",
                    severity="normal",
                    coins=(coin,),
                    cooldown_key=f"exposure:{coin}",
                    metrics={
                        "current_position_share_pct_of_exposure_budget": current_share,
                        "target_band": band,
                    },
                )
        return None

    def _detect_reference_proxy(
        self,
        *,
        state: dict[str, Any],
        market: DataIngestBundle,
        now: datetime,
    ) -> RTTriggerDecision | None:
        for position in market.portfolio.positions:
            coin = str(position.coin).upper()
            notional = _to_decimal(position.notional_usd)
            pnl = _to_decimal(position.unrealized_pnl_usd)
            if notional > 0 and abs(pnl / notional) >= Decimal("0.01"):
                return RTTriggerDecision(
                    reason="reference_tp_sl_proxy",
                    severity="normal",
                    coins=(coin,),
                    cooldown_key=f"reference:{coin}:pnl_move",
                    metrics={
                        "unrealized_pnl_usd": str(pnl),
                        "notional_usd": str(notional),
                        "pnl_pct_of_notional": float(pnl / notional * Decimal("100")),
                    },
                )
            context = market.market_context.get(coin)
            snapshot = market.market.get(coin)
            if context is None or snapshot is None:
                continue
            mark = _to_decimal(snapshot.mark_price)
            for level in context.key_levels:
                if level.source not in {"1h", "4h"}:
                    continue
                price = _to_decimal(level.price)
                if price <= 0:
                    continue
                distance_pct = abs(mark - price) / price * Decimal("100")
                if distance_pct <= Decimal("0.20"):
                    return RTTriggerDecision(
                        reason="reference_tp_sl_proxy",
                        severity="normal",
                        coins=(coin,),
                        cooldown_key=f"reference:{coin}:near_{level.label}",
                        metrics={"mark_price": str(mark), "key_level": level.model_dump(mode="json"), "distance_pct": float(distance_pct)},
                    )
        return None

    def _detect_heartbeat(
        self,
        *,
        state: dict[str, Any],
        market: DataIngestBundle,
        now: datetime,
    ) -> RTTriggerDecision | None:
        last_trigger = _parse_datetime(state.get("last_trigger_at_utc"))
        has_position = bool(market.portfolio.positions)
        interval = timedelta(
            minutes=(
                self.config.position_heartbeat_minutes
                if has_position
                else self.config.flat_heartbeat_minutes
            )
        )
        if last_trigger is None or now - last_trigger >= interval:
            return RTTriggerDecision(
                reason="heartbeat",
                severity="low",
                cooldown_key="heartbeat:position" if has_position else "heartbeat:flat",
                metrics={"has_position": has_position, "interval_minutes": interval.total_seconds() / 60},
            )
        return None

    def _handle_decision(
        self,
        decision: RTTriggerDecision,
        *,
        state: dict[str, Any],
        now: datetime,
        trace_id: str,
    ) -> dict[str, Any]:
        event_id = new_id("rt_trigger")
        skipped_reason = self._cooldown_skip_reason(decision=decision, state=state, now=now)
        cron_running = False
        run_result: CronRunResult | None = None
        dispatched = False
        if skipped_reason is None:
            cron_running = self.cron_runner.is_running(job_id=self.config.rt_job_id)
            if cron_running:
                skipped_reason = "cron_running"
            else:
                run_result = self.cron_runner.run_now(job_id=self.config.rt_job_id)
                dispatched = bool(run_result.ok)
                if not dispatched:
                    skipped_reason = "cron_run_failed"
        payload = {
            "trigger_id": event_id,
            "detected_at_utc": now.isoformat(),
            "reason": decision.reason,
            "severity": decision.severity,
            "coins": list(decision.coins),
            "cooldown_key": decision.cooldown_key,
            "bypass_cooldown": decision.bypass_cooldown,
            "metrics": decision.metrics,
            "source_asset_ids": [item for item in decision.source_asset_ids if item],
            "rt_cron_job_id": self.config.rt_job_id,
            "dispatched": dispatched,
            "skipped_reason": skipped_reason,
            "cron_running": cron_running,
            "cron_stdout": _truncate(run_result.stdout if run_result else "", 800),
            "cron_stderr": _truncate(run_result.stderr if run_result else "", 800),
            "cron_returncode": run_result.returncode if run_result else None,
        }
        self.memory_assets.save_asset(
            asset_type="rt_trigger_event",
            asset_id=event_id,
            payload=payload,
            trace_id=trace_id,
            actor_role="system",
            group_key=decision.reason,
            metadata={"dispatched": dispatched, "skipped_reason": skipped_reason},
        )
        envelope = EventFactory.build(
            trace_id=trace_id,
            event_type=EVENT_RT_TRIGGER_DETECTED,
            source_module=MODULE_NAME,
            entity_type="rt_trigger_event",
            entity_id=event_id,
            payload=payload,
        )
        self.memory_assets.append_event(envelope)
        if self.event_bus is not None:
            try:
                self.event_bus.publish(envelope)
            except Exception:
                pass
        return payload

    def _cooldown_skip_reason(self, *, decision: RTTriggerDecision, state: dict[str, Any], now: datetime) -> str | None:
        if decision.bypass_cooldown:
            return None
        last_trigger = _parse_datetime(state.get("last_trigger_at_utc"))
        if last_trigger is not None and now - last_trigger < timedelta(seconds=self.config.global_cooldown_seconds):
            return "global_cooldown"
        by_key = dict(state.get("last_trigger_by_key") or {})
        last_by_key = _parse_datetime(by_key.get(decision.cooldown_key))
        if last_by_key is not None and now - last_by_key < timedelta(seconds=self.config.key_cooldown_seconds):
            return "key_cooldown"
        if len(self._recent_trigger_times(state, now=now)) >= int(self.config.max_runs_per_hour):
            return "hourly_limit"
        return None

    def _load_state(self) -> dict[str, Any]:
        asset = self.memory_assets.get_asset("rt_trigger_state")
        if asset is None:
            return {}
        payload = asset.get("payload")
        return dict(payload or {}) if isinstance(payload, dict) else {}

    def _save_state(self, payload: dict[str, Any], *, trace_id: str) -> None:
        self.memory_assets.save_asset(
            asset_type="rt_trigger_state",
            asset_id="rt_trigger_state",
            payload=payload,
            trace_id=trace_id,
            actor_role="system",
            group_key="risk_trader",
        )

    def _updated_state_after_scan(
        self,
        *,
        state: dict[str, Any],
        market: DataIngestBundle,
        now: datetime,
    ) -> dict[str, Any]:
        updated = dict(state)
        updated["last_scan_at_utc"] = now.isoformat()
        latest_strategy = self.memory_assets.get_latest_strategy()
        if latest_strategy is not None:
            updated["last_seen_strategy_key"] = self._strategy_key(dict(latest_strategy.get("payload") or {}))
        event_ids = set(updated.get("last_seen_event_ids") or [])
        for asset_type in ("macro_event", "news_submission"):
            for asset in self.memory_assets.recent_assets(asset_type=asset_type, limit=50):
                asset_id = str(asset.get("asset_id") or "")
                if asset_id:
                    event_ids.add(asset_id)
        updated["last_seen_event_ids"] = sorted(event_ids)[-200:]
        execution_ids = set(updated.get("last_seen_execution_result_ids") or [])
        for asset in self.memory_assets.recent_assets(asset_type="execution_result", actor_role="risk_trader", limit=50):
            asset_id = str(asset.get("asset_id") or "")
            if asset_id and self._execution_result_ready_for_followup(asset, now=now):
                execution_ids.add(asset_id)
        updated["last_seen_execution_result_ids"] = sorted(execution_ids)[-200:]
        updated["last_market_state_by_coin"] = {
            coin: self._market_state(coin=coin, context=context, mark_price=market.market[coin].mark_price)
            for coin, context in market.market_context.items()
            if coin in market.market
        }
        updated["recent_trigger_times_utc"] = self._recent_trigger_times(updated, now=now)
        return updated

    def _recent_trigger_times(self, state: dict[str, Any], *, now: datetime) -> list[str]:
        cutoff = now - timedelta(hours=1)
        recent: list[str] = []
        for raw in list(state.get("recent_trigger_times_utc") or []):
            parsed = _parse_datetime(raw)
            if parsed is not None and parsed >= cutoff:
                recent.append(parsed.isoformat())
        return recent

    def _eligible_coins(self, market: DataIngestBundle) -> set[str]:
        eligible = {str(position.coin).upper() for position in market.portfolio.positions}
        latest = self.memory_assets.get_latest_strategy()
        payload = dict((latest or {}).get("payload") or {})
        for target in list(payload.get("targets") or []):
            if not isinstance(target, dict):
                continue
            coin = str(target.get("symbol") or "").upper()
            if not coin:
                continue
            state = str(target.get("state") or "").lower()
            direction = str(target.get("direction") or "").lower()
            band = self._numeric_band(target.get("target_exposure_band_pct"))
            upper = band[1] if band is not None else 0.0
            if state in {"active", "reduce"} or (direction in {"long", "short"} and upper > 0):
                eligible.add(coin)
        return eligible

    def _market_state(self, *, coin: str, context: MarketContextNormalized, mark_price: str) -> dict[str, Any]:
        levels = {level.label: float(_to_decimal(level.price)) for level in context.key_levels}
        return {
            "coin": coin,
            "mark_price": float(_to_decimal(mark_price)),
            "breakout_state": context.breakout_retest_state.state,
            "volatility_state": context.volatility_state.state,
            "1h_high": levels.get("1h_high"),
            "1h_low": levels.get("1h_low"),
            "4h_high": levels.get("4h_high"),
            "4h_low": levels.get("4h_low"),
        }

    @staticmethod
    def _crossed_one_hour_level(previous: dict[str, Any], current: dict[str, Any]) -> str | None:
        prev_mark = previous.get("mark_price")
        current_mark = current.get("mark_price")
        if prev_mark is None or current_mark is None:
            return None
        for label in ("1h_high", "1h_low"):
            level = current.get(label)
            prev_level = previous.get(label) or level
            if level is None or prev_level is None:
                continue
            if float(prev_mark) < float(prev_level) <= float(current_mark):
                return f"crossed_above_{label}"
            if float(prev_mark) > float(prev_level) >= float(current_mark):
                return f"crossed_below_{label}"
        return None

    def _gross_exposure_pct(self, market: DataIngestBundle) -> float:
        equity = _to_decimal(market.portfolio.total_equity_usd)
        total_exposure = _to_decimal(market.portfolio.total_exposure_usd)
        leverage = _to_decimal(self.config.max_leverage)
        budget = equity * leverage
        if budget <= 0:
            return 0.0
        return float(total_exposure / budget * Decimal("100"))

    @staticmethod
    def _outside_band_by(value: float, band: tuple[float, float], threshold: float) -> bool:
        lower, upper = band
        return value < lower - threshold or value > upper + threshold

    @staticmethod
    def _numeric_band(raw: Any) -> tuple[float, float] | None:
        if not isinstance(raw, (list, tuple)) or len(raw) < 2:
            return None
        try:
            lower = float(raw[0])
            upper = float(raw[1])
        except (TypeError, ValueError):
            return None
        return (lower, upper)

    @staticmethod
    def _strategy_key(payload: dict[str, Any]) -> str:
        strategy_id = str(payload.get("strategy_id") or "").strip()
        revision = str(payload.get("revision_number") or "").strip()
        if strategy_id or revision:
            return f"{strategy_id}:{revision}"
        return ""

    @staticmethod
    def _asset_news_severity(asset: dict[str, Any]) -> str:
        payload = dict(asset.get("payload") or {})
        values = [
            payload.get("impact_level"),
            payload.get("severity"),
        ]
        for item in list(payload.get("events") or []):
            if isinstance(item, dict):
                values.append(item.get("impact_level"))
                values.append(item.get("severity"))
        for value in values:
            text = str(value or "").strip().lower()
            if text in {"critical", "high"}:
                return text
        return "medium"

    def _execution_result_ready_for_followup(self, asset: dict[str, Any], *, now: datetime) -> bool:
        payload = dict(asset.get("payload") or {})
        if not bool(payload.get("success")) or not list(payload.get("fills") or []):
            return True
        executed_at = _parse_datetime(payload.get("executed_at") or asset.get("created_at"))
        if executed_at is None:
            return True
        return now - executed_at >= timedelta(seconds=self.config.execution_followup_delay_seconds)


def _parse_datetime(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return _as_utc(raw)
    try:
        return _as_utc(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))
    except Exception:
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _to_decimal(raw: Any) -> Decimal:
    try:
        return Decimal(str(raw or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _truncate(value: str, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else f"{text[:limit]}..."
