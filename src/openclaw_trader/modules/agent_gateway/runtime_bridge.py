from __future__ import annotations

import copy
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event, Lock, Thread
from typing import TYPE_CHECKING, Any

from ...shared.utils import new_id

# 2026-04-25 temporary: log per-phase wall time inside refresh_once so we
# can find the remaining ~80s overhead after market_data parallelization.
# Set OPENCLAW_BRIDGE_TIMING=1 to enable; off by default so it cannot
# accidentally pollute production logs after this debugging pass.
_BRIDGE_TIMING_ENABLED = os.environ.get("OPENCLAW_BRIDGE_TIMING", "").lower() in {"1", "true", "yes"}


def _bt_print(msg: str) -> None:
    if _BRIDGE_TIMING_ENABLED:
        print(f"[bridge-timing] {msg}", file=sys.stderr, flush=True)
from ..news_events.models import NewsDigestEvent
from ..news_events.service import NewsEventService
from ..policy_risk.service import PolicyRiskService
from ..quant_intelligence.service import QuantIntelligenceService
from ..memory_assets.service import MemoryAssetsService
from ..trade_gateway.macro_data.models import MacroSnapshot
from ..trade_gateway.macro_data.service import MacroDataService
from ..trade_gateway.market_data.models import DataIngestBundle
from ..trade_gateway.market_data.service import DataIngestService

if TYPE_CHECKING:
    from .service import AgentGatewayService


@dataclass(frozen=True)
class RuntimeBridgeConfig:
    enabled: bool = True
    refresh_interval_seconds: int = 10
    max_age_seconds: int = 30


class RuntimeBridgeMonitor:
    def __init__(
        self,
        *,
        memory_assets: MemoryAssetsService,
        market_data: DataIngestService,
        news_events: NewsEventService,
        quant_intelligence: QuantIntelligenceService,
        policy_risk: PolicyRiskService,
        gateway: AgentGatewayService,
        config: RuntimeBridgeConfig | None = None,
        macro_data: MacroDataService | None = None,
    ) -> None:
        self.memory_assets = memory_assets
        self.market_data = market_data
        self.news_events = news_events
        self.quant_intelligence = quant_intelligence
        self.policy_risk = policy_risk
        self.gateway = gateway
        self.macro_data = macro_data
        self.config = config or RuntimeBridgeConfig()
        self._stop = Event()
        self._thread: Thread | None = None
        self._lock = Lock()
        self._latest_asset: dict[str, Any] | None = None

    def start(self) -> None:
        if not self.config.enabled or self._thread is not None:
            return
        self._thread = Thread(target=self._loop, name="agent-gateway-runtime-bridge", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def latest_asset(self, *, max_age_seconds: int | None = None) -> dict[str, Any] | None:
        with self._lock:
            asset = copy.deepcopy(self._latest_asset)
        if asset is None:
            asset = self.memory_assets.get_runtime_bridge_state_asset(max_age_seconds=max_age_seconds)
        elif max_age_seconds is not None and self._asset_age_seconds(asset) > max_age_seconds:
            asset = self.memory_assets.get_runtime_bridge_state_asset(max_age_seconds=max_age_seconds)
        return asset

    def refresh_once(
        self,
        *,
        reason: str = "scheduled",
        trace_id: str | None = None,
        force_sync_news: bool = False,
    ) -> dict[str, Any]:
        trace = trace_id or new_id("trace")
        t_start = time.monotonic()
        t0 = t_start
        (
            market,
            news,
            latest_strategy_asset,
            prior_risk_state,
            macro_memory,
            macro_snapshot,
        ) = self._collect_primitives(
            trace_id=trace,
            force_sync_news=force_sync_news,
        )
        t_primitives = time.monotonic() - t0
        t0 = time.monotonic()
        latest_strategy = (
            latest_strategy_asset["payload"]
            if latest_strategy_asset and "payload" in latest_strategy_asset
            else latest_strategy_asset
        )
        forecasts = self.quant_intelligence.get_latest_forecasts(market)
        t_forecasts = time.monotonic() - t0
        t0 = time.monotonic()
        policies = self.policy_risk.evaluate(
            market=market,
            forecasts=forecasts,
            news_events=news,
            prior_risk_state=dict((prior_risk_state or {}).get("payload") or {}),
            latest_strategy=latest_strategy or {},
        )
        t_policies = time.monotonic() - t0
        t0 = time.monotonic()
        runtime_inputs = self.gateway.build_runtime_inputs(
            trace_id=trace,
            market=market,
            policies=policies,
            forecasts=forecasts,
            news_events=news,
            latest_strategy=latest_strategy,
            macro_memory=macro_memory,
            macro_snapshot=macro_snapshot,
        )
        t_build_inputs = time.monotonic() - t0
        t0 = time.monotonic()
        now = datetime.now(UTC)
        payload = {
            "state_id": new_id("runtime_bridge_state"),
            "refreshed_at_utc": now.isoformat(),
            "refresh_reason": reason,
            "source_timestamps": self._source_timestamps(
                market=market,
                news=news,
                latest_strategy=latest_strategy,
                prior_risk_state=prior_risk_state,
                refreshed_at=now,
            ),
            "context": {
                "market": market.model_dump(mode="json"),
                "news": [item.model_dump(mode="json") for item in news],
                "forecasts": {coin: forecast.model_dump(mode="json") for coin, forecast in forecasts.items()},
                "policies": {coin: policy.model_dump(mode="json") for coin, policy in policies.items()},
                "latest_strategy": latest_strategy or {},
                "macro_memory": list(macro_memory or []),
                "macro_prices": macro_snapshot.model_dump(mode="json") if macro_snapshot else {},
            },
            "runtime_inputs": {
                role: {
                    "task_kind": runtime_input.task_kind,
                    "payload": runtime_input.payload,
                }
                for role, runtime_input in runtime_inputs.items()
            },
        }
        t_payload_assemble = time.monotonic() - t0
        t0 = time.monotonic()
        self._persist_portfolio_snapshot(trace_id=trace, market=market, reason=reason)
        t_persist_portfolio = time.monotonic() - t0
        t0 = time.monotonic()
        asset = self.memory_assets.materialize_runtime_bridge_state(
            trace_id=trace,
            authored_payload=payload,
            metadata={"refresh_reason": reason},
        )
        t_persist_bridge = time.monotonic() - t0
        with self._lock:
            self._latest_asset = copy.deepcopy(asset)
        t_total = time.monotonic() - t_start
        _bt_print(
            f"refresh_once reason={reason} total={t_total:.2f}s "
            f"primitives={t_primitives:.2f}s "
            f"forecasts={t_forecasts:.2f}s "
            f"policies={t_policies:.2f}s "
            f"build_inputs={t_build_inputs:.2f}s "
            f"payload_assemble={t_payload_assemble:.2f}s "
            f"persist_portfolio={t_persist_portfolio:.2f}s "
            f"persist_bridge={t_persist_bridge:.2f}s"
        )
        return asset

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.refresh_once(reason="scheduled")
            except Exception:
                pass
            if self._stop.wait(max(int(self.config.refresh_interval_seconds), 1)):
                break

    def _collect_primitives(
        self,
        *,
        trace_id: str,
        force_sync_news: bool,
    ) -> tuple[
        DataIngestBundle,
        list[NewsDigestEvent],
        dict[str, Any] | None,
        dict[str, Any] | None,
        list[dict[str, Any]],
        MacroSnapshot | None,
    ]:
        def _timed(label: str, fn, *args, **kwargs):
            t0 = time.monotonic()
            try:
                result = fn(*args, **kwargs)
                _bt_print(f"  primitive {label} done={time.monotonic()-t0:.2f}s")
                return result
            except Exception as exc:
                _bt_print(f"  primitive {label} ERR={time.monotonic()-t0:.2f}s err={type(exc).__name__}")
                raise

        with ThreadPoolExecutor(max_workers=6) as executor:
            market_future = executor.submit(_timed, "market", self.market_data.get_market_overview, trace_id=trace_id)
            news_future = executor.submit(_timed, "news", self.news_events.get_latest_news_batch, force_sync=force_sync_news)
            strategy_future = executor.submit(_timed, "strategy", self.memory_assets.get_latest_strategy)
            risk_state_future = executor.submit(_timed, "risk_state", self.memory_assets.get_asset, "risk_brake_state")
            macro_memory_future = executor.submit(_timed, "macro_memory", self.memory_assets.get_macro_memory)
            macro_future = executor.submit(_timed, "macro_snapshot", self._safe_collect_macro_snapshot)
            market = market_future.result()
            news = news_future.result()
            latest_strategy_asset = strategy_future.result()
            prior_risk_state = risk_state_future.result()
            macro_memory = macro_memory_future.result()
            macro_snapshot = macro_future.result()
        return market, news, latest_strategy_asset, prior_risk_state, macro_memory, macro_snapshot

    def _safe_collect_macro_snapshot(self) -> MacroSnapshot | None:
        if self.macro_data is None:
            return None
        try:
            return self.macro_data.collect_snapshot()
        except Exception:
            return None

    def _persist_portfolio_snapshot(self, *, trace_id: str, market: DataIngestBundle, reason: str) -> None:
        portfolio_payload = market.portfolio.model_dump(mode="json")
        self.memory_assets.save_portfolio(trace_id, portfolio_payload)
        self.memory_assets.save_asset(
            asset_type="portfolio_snapshot",
            payload=portfolio_payload,
            trace_id=trace_id,
            actor_role="system",
            group_key=trace_id,
            metadata={
                "reason": "runtime_bridge_refresh",
                "refresh_reason": reason,
            },
        )

    @staticmethod
    def _source_timestamps(
        *,
        market: DataIngestBundle,
        news: list[NewsDigestEvent],
        latest_strategy: dict[str, Any] | None,
        prior_risk_state: dict[str, Any] | None,
        refreshed_at: datetime,
    ) -> dict[str, Any]:
        latest_news_time = None
        if news:
            latest_news_time = max(
                (
                    item.published_at.astimezone(UTC).isoformat()
                    if item.published_at.tzinfo is not None
                    else item.published_at.replace(tzinfo=UTC).isoformat()
                )
                for item in news
            )
        strategy_generated_at = None
        if isinstance(latest_strategy, dict):
            strategy_generated_at = latest_strategy.get("generated_at_utc")
        return {
            "refreshed_at_utc": refreshed_at.isoformat(),
            "market_captured_at_utc": market.portfolio.captured_at.astimezone(UTC).isoformat()
            if market.portfolio.captured_at.tzinfo is not None
            else market.portfolio.captured_at.replace(tzinfo=UTC).isoformat(),
            "latest_news_published_at_utc": latest_news_time,
            "latest_strategy_generated_at_utc": strategy_generated_at,
            "risk_brake_state_updated_at_utc": (prior_risk_state or {}).get("created_at"),
        }

    @staticmethod
    def _asset_age_seconds(asset: dict[str, Any]) -> float:
        payload = dict(asset.get("payload") or {})
        raw_timestamp = payload.get("refreshed_at_utc") or asset.get("created_at")
        try:
            refreshed_at = datetime.fromisoformat(str(raw_timestamp).replace("Z", "+00:00"))
        except Exception:
            return float("inf")
        if refreshed_at.tzinfo is None:
            refreshed_at = refreshed_at.replace(tzinfo=UTC)
        return (datetime.now(UTC) - refreshed_at.astimezone(UTC)).total_seconds()
