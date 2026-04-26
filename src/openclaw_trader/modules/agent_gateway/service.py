from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ...shared.infra.bus import EventBus
from ...shared.protocols import EventFactory
from ...shared.utils import new_id, notional_to_pct_of_exposure_budget
from ..news_events.models import NewsDigestEvent
from ..news_events.service import NewsEventService
from ..notification_service.service import NotificationService
from ..policy_risk.models import GuardDecision
from ..policy_risk.service import PolicyRiskService
from ..quant_intelligence.models import CoinForecast
from ..quant_intelligence.service import QuantIntelligenceService
from ..memory_assets.service import MemoryAssetsService
from ..trade_gateway.execution.service import ExecutionGatewayService
from ..trade_gateway.execution.models import ExecutionDecision
from ..trade_gateway.market_data.models import DataIngestBundle
from ..trade_gateway.market_data.service import DataIngestService
from .events import (
    EVENT_AGENT_SESSION_RESET,
    EVENT_SUBMISSION_REJECTED,
    EVENT_SUBMISSION_VALIDATED,
    MODULE_NAME,
)
from .models import (
    AgentReply,
    AgentRuntimeLease,
    AgentRuntimeInput,
    AgentRuntimePack,
    AgentTask,
    DirectAgentReminder,
    ExecutionSubmission,
    MacroBriefSubmission,
    NewsSubmission,
    RetroBriefSubmission,
    RetroLearningAck,
    RetroSubmission,
    StrategySubmission,
    ValidatedSubmissionEnvelope,
)
from .ports import AgentRunner
from .ports import AgentSessionController
from .ports import TriggerContextBridge


class SubmissionValidationError(ValueError):
    def __init__(
        self,
        *,
        schema_ref: str,
        prompt_ref: str,
        errors: list[str],
        error_kind: str = "agent_invalid_submission",
        raw_reply: str | None = None,
        stderr_summary: str | None = None,
    ) -> None:
        super().__init__("submission_validation_failed")
        self.schema_ref = schema_ref
        self.prompt_ref = prompt_ref
        self.errors = errors
        self.error_kind = error_kind
        self.raw_reply = raw_reply
        self.stderr_summary = stderr_summary


class SubmissionTriggerResult:
    """Spec 015 scenario 2 verification: submit-gate check result.

    Kept as a lightweight object (no pydantic/dataclass) so tests can
    construct fakes without pulling pydantic schema churn.
    """

    __slots__ = ("internal_reasoning_only", "hits", "details")

    def __init__(
        self,
        *,
        internal_reasoning_only: bool,
        hits: list[str],
        details: dict[str, Any],
    ) -> None:
        self.internal_reasoning_only = bool(internal_reasoning_only)
        self.hits = list(hits or [])
        self.details = dict(details or {})


class RuntimeInputLeaseError(ValueError):
    def __init__(self, *, reason: str, input_id: str, agent_role: str, detail: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.input_id = input_id
        self.agent_role = agent_role
        self.detail = detail


class AgentGatewayService:
    _STRATEGY_SCHEMA_REF = "specs/modules/agent_gateway/contracts/strategy.schema.json"
    _STRATEGY_PROMPT_REF = "specs/modules/agent_gateway/contracts/strategy.prompt.md"
    _EXECUTION_SCHEMA_REF = "specs/modules/agent_gateway/contracts/execution.schema.json"
    _EXECUTION_PROMPT_REF = "specs/modules/agent_gateway/contracts/execution.prompt.md"
    _NEWS_SCHEMA_REF = "specs/modules/agent_gateway/contracts/news.schema.json"
    _NEWS_PROMPT_REF = "specs/modules/agent_gateway/contracts/news.prompt.md"
    _MACRO_BRIEF_SCHEMA_REF = "specs/modules/agent_gateway/contracts/macro_brief.schema.json"
    _MACRO_BRIEF_PROMPT_REF = "specs/modules/agent_gateway/contracts/macro_brief.prompt.md"
    _RETRO_BRIEF_SPEC_REF_BY_ROLE = {
        "pm": "specs/agents/pm/spec.md",
        "risk_trader": "specs/agents/risk_trader/spec.md",
        "macro_event_analyst": "specs/agents/macro_event_analyst/spec.md",
    }
    _RETRO_BRIEF_PROMPT_REF_BY_ROLE = {
        "pm": "skills/pm-strategy-cycle/SKILL.md",
        "risk_trader": "skills/risk-trader-decision/SKILL.md",
        "macro_event_analyst": "skills/mea-event-review/SKILL.md",
    }
    _CHIEF_RETRO_SPEC_REF = "specs/agents/crypto_chief/spec.md"
    _CHIEF_RETRO_PROMPT_REF = "skills/chief-retro-and-summary/SKILL.md"
    _PM_TRIGGER_EVENT_TYPE = "workflow.pm_trigger.detected"
    _PM_TRIGGER_TYPE_ALIASES = {
        "daily_main": "pm_main_cron",
        "cadence": "pm_main_cron",
        "event": "agent_message",
        "event_driven": "agent_message",
        "mea_event": "agent_message",
    }
    _PM_TRIGGER_CATEGORY_BY_TYPE = {
        "pm_main_cron": "cadence",
        "scheduled_recheck": "workflow",
        "risk_brake": "workflow",
        "agent_message": "message",
        "manual": "manual",
        "pm_unspecified": "unknown",
    }

    def __init__(
        self,
        *,
        pm_runner: AgentRunner,
        risk_runner: AgentRunner,
        macro_runner: AgentRunner,
        chief_runner: AgentRunner,
        session_controller: AgentSessionController | None = None,
        agent_name_by_role: dict[str, str] | None = None,
        learning_path_by_role: dict[str, str] | None = None,
        memory_assets: MemoryAssetsService | None = None,
        market_data: DataIngestService | None = None,
        news_events: NewsEventService | None = None,
        quant_intelligence: QuantIntelligenceService | None = None,
        policy_risk: PolicyRiskService | None = None,
        trade_execution: ExecutionGatewayService | None = None,
        notification_service: NotificationService | None = None,
        trigger_bridge: TriggerContextBridge | None = None,
        event_bus: EventBus | None = None,
        runtime_pack_ttl_seconds: int = 900,
        runtime_dispatcher: Any | None = None,
        runtime_bridge_max_age_seconds: int | None = None,
    ) -> None:
        self.pm_runner = pm_runner
        self.risk_runner = risk_runner
        self.macro_runner = macro_runner
        self.chief_runner = chief_runner
        self.session_controller = session_controller
        self.agent_name_by_role = dict(agent_name_by_role or self._DEFAULT_AGENT_NAME_BY_ROLE)
        self.learning_path_by_role = dict(learning_path_by_role or self._DEFAULT_LEARNING_PATH_BY_ROLE)
        self.memory_assets = memory_assets
        self.market_data = market_data
        self.news_events = news_events
        self.quant_intelligence = quant_intelligence
        self.policy_risk = policy_risk
        self.trade_execution = trade_execution
        self.notification_service = notification_service
        self.trigger_bridge = trigger_bridge
        self.event_bus = event_bus
        self.runtime_pack_ttl_seconds = runtime_pack_ttl_seconds
        self.runtime_dispatcher = runtime_dispatcher
        self.runtime_bridge_monitor: Any | None = None
        self.runtime_bridge_max_age_seconds = runtime_bridge_max_age_seconds

    def bind_runtime_dispatcher(self, runtime_dispatcher: Any) -> None:
        self.runtime_dispatcher = runtime_dispatcher

    def bind_runtime_bridge_monitor(self, runtime_bridge_monitor: Any, *, max_age_seconds: int | None = None) -> None:
        self.runtime_bridge_monitor = runtime_bridge_monitor
        if max_age_seconds is not None:
            self.runtime_bridge_max_age_seconds = max_age_seconds

    def session_id_for_role(self, agent_role: str) -> str:
        session_id = self._resolve_openclaw_main_session_id(agent_role)
        if session_id:
            return session_id
        return self._SESSION_ID_BY_ROLE.get(agent_role, f"{agent_role}-session")

    def pull_pm_runtime_input(
        self,
        *,
        trigger_type: str = "pm_unspecified",
        params: dict[str, object] | None = None,
    ) -> AgentRuntimePack:
        return self._issue_runtime_pack(agent_role="pm", task_kind="strategy", trigger_type=trigger_type, params=params)

    def pull_rt_runtime_input(
        self,
        *,
        trigger_type: str = "cadence",
        params: dict[str, object] | None = None,
    ) -> AgentRuntimePack:
        return self._issue_runtime_pack(agent_role="risk_trader", task_kind="execution", trigger_type=trigger_type, params=params)

    def pull_mea_runtime_input(
        self,
        *,
        trigger_type: str = "cadence",
        params: dict[str, object] | None = None,
    ) -> AgentRuntimePack:
        return self._issue_runtime_pack(
            agent_role="macro_event_analyst",
            task_kind="event_summary",
            trigger_type=trigger_type,
            params=params,
        )

    def pull_chief_retro_pack(
        self,
        *,
        trigger_type: str = "daily_retro",
        params: dict[str, object] | None = None,
    ) -> AgentRuntimePack:
        return self._issue_runtime_pack(agent_role="crypto_chief", task_kind="retro", trigger_type=trigger_type, params=params)

    def pull_chief_macro_brief_pack(
        self,
        *,
        trigger_type: str = "daily_macro_brief",
        params: dict[str, object] | None = None,
    ) -> AgentRuntimePack:
        """Chief's prospective daily macro brief pack (spec 014).

        Distinct from weekly retro. Carries:
        - prior brief for self-review + falsification tracking
        - macro_prices / news_events / macro_memory as context
        - digital_oracle preset hint
        """
        return self._issue_runtime_pack(
            agent_role="crypto_chief",
            task_kind="macro_brief",
            trigger_type=trigger_type,
            params=params,
        )

    # --------------------------------------------------------------
    # Spec 015 submit-gate config: thresholds intentionally module-
    # level so ops / tests can monkey-patch. FR-005 says they must be
    # overridable from settings.orchestrator.pm_submit_gate_*; that
    # wiring lands later via config.loader. For MVP we keep the
    # numbers here and consult settings.orchestrator if available.
    # --------------------------------------------------------------
    _PM_SUBMIT_GATE_PRICE_BREACH_PCT_DEFAULT = 1.5
    _PM_SUBMIT_GATE_OWNER_WAKE_SOURCES = frozenset({"manual", "owner_push"})

    def submit_strategy(
        self,
        *,
        input_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        lease = self._validate_runtime_lease(input_id=input_id, agent_role="pm")
        envelope = self.validate_submission(
            submission_kind="strategy",
            agent_role="pm",
            trace_id=lease.pack.trace_id,
            payload=payload,
        )
        previous_strategy_asset = (
            self.memory_assets.latest_asset(asset_type="strategy", actor_role="pm")
            or self.memory_assets.latest_asset(asset_type="strategy")
        )
        trigger_result = self.evaluate_strategy_submission_triggers(
            lease=lease,
            previous_strategy_asset=previous_strategy_asset,
        )
        change_summary = dict(envelope.payload.get("change_summary") or {})
        why_no_external_trigger = str(change_summary.get("why_no_external_trigger") or "").strip()
        if trigger_result.internal_reasoning_only and not why_no_external_trigger:
            schema_ref, prompt_ref = self._submission_contract("strategy")
            raise SubmissionValidationError(
                schema_ref=schema_ref,
                prompt_ref=prompt_ref,
                errors=[
                    (
                        "hesitation_unjustified: this revision has no external trigger "
                        "(no new MEA event, no price_breach > "
                        f"{self._pm_submit_gate_price_breach_pct_threshold():.2f}%, no quant flip, "
                        "no risk_brake, no owner push). Either wait for a real signal, or "
                        "re-submit with `change_summary.why_no_external_trigger` populated "
                        "(self-interrogation text; not a boilerplate reason)."
                    )
                ],
                error_kind="hesitation_unjustified",
            )
        # Persist current market/forecast snapshot onto the new strategy so
        # the NEXT submit can diff against it (spec 015 FR-003).
        current_market_snapshot = self._snapshot_market_for_submit_gate(lease)
        current_forecast_snapshot = self._snapshot_forecasts_for_submit_gate(lease)
        canonical_authored = dict(envelope.payload)
        canonical_authored["internal_reasoning_only"] = bool(trigger_result.internal_reasoning_only)
        strategy_payload = self.memory_assets.materialize_strategy_asset(
            trace_id=lease.pack.trace_id,
            authored_payload=canonical_authored,
            trigger_type=lease.pack.trigger_type,
            actor_role="pm",
            source_ref=envelope.envelope_id,
        )
        # Stash gate inputs/outputs in asset metadata so next-submit can
        # diff + retro / observability can replay the gate decision.
        strategy_id = str(strategy_payload.get("strategy_id") or "")
        if strategy_id:
            strategy_asset = self.memory_assets.get_asset(strategy_id)
            if strategy_asset is not None:
                existing_metadata = dict(strategy_asset.get("metadata") or {})
                existing_metadata.update(
                    {
                        "submit_gate": {
                            "hits": list(trigger_result.hits),
                            "internal_reasoning_only": bool(trigger_result.internal_reasoning_only),
                            "details": dict(trigger_result.details),
                        },
                        "submit_market_snapshot": current_market_snapshot,
                        "submit_forecast_snapshot": current_forecast_snapshot,
                    }
                )
                self.memory_assets.save_asset(
                    asset_type="strategy",
                    asset_id=strategy_id,
                    payload=strategy_payload,
                    trace_id=lease.pack.trace_id,
                    actor_role="pm",
                    group_key=str(strategy_payload.get("strategy_day_utc") or ""),
                    source_ref=envelope.envelope_id,
                    metadata=existing_metadata,
                )
        latest_pm_trigger_event = (
            dict(lease.pack.payload.get("latest_pm_trigger_event"))
            if isinstance(lease.pack.payload.get("latest_pm_trigger_event"), dict)
            else None
        )
        event_payload = {
            "strategy": strategy_payload,
            "envelope_id": envelope.envelope_id,
            "trigger_type": lease.pack.trigger_type,
            "internal_reasoning_only": bool(trigger_result.internal_reasoning_only),
            "submit_gate_hits": list(trigger_result.hits),
            "latest_pm_trigger_event": latest_pm_trigger_event,
            "trigger_reason": (
                str(latest_pm_trigger_event.get("reason") or "").strip()
                if latest_pm_trigger_event is not None
                else None
            ),
            "wake_source": (
                str(latest_pm_trigger_event.get("wake_source") or "").strip()
                if latest_pm_trigger_event is not None
                else None
            ),
            "source_role": (
                str(latest_pm_trigger_event.get("source_role") or "").strip()
                if latest_pm_trigger_event is not None
                else None
            ),
            "input_id": input_id,
        }
        # FR-006: silent notification for internal_reasoning_only. The
        # strategy.submitted event still fires (observability needs it) but
        # `internal_reasoning_only=true` on the event payload gates both
        # the notification_service dispatch and the RT wake detector.
        self._record_events(
            [
                self.build_submission_event(trace_id=lease.pack.trace_id, envelope=envelope),
                EventFactory.build(
                    trace_id=lease.pack.trace_id,
                    event_type="strategy.submitted",
                    source_module="agent_gateway",
                    entity_type="strategy",
                    entity_id=str(strategy_payload.get("strategy_id")),
                    payload=event_payload,
                ),
            ]
        )
        self.memory_assets.save_agent_session(
            agent_role="pm",
            session_id=self.session_id_for_role("pm"),
            last_task_kind="strategy",
            last_submission_kind="strategy",
        )
        self._consume_runtime_lease(lease=lease, submission_kind="strategy")
        if self.trigger_bridge is not None:
            self.trigger_bridge.record_recheck_state(
                trace_id=lease.pack.trace_id,
                strategy_id=str(strategy_payload.get("strategy_id")),
                rechecks=list(strategy_payload.get("scheduled_rechecks") or []),
            )
        return {
            "trace_id": lease.pack.trace_id,
            "input_id": input_id,
            "envelope": envelope.model_dump(mode="json"),
            "strategy": strategy_payload,
            "internal_reasoning_only": bool(trigger_result.internal_reasoning_only),
            "submit_gate_hits": list(trigger_result.hits),
        }

    def evaluate_strategy_submission_triggers(
        self,
        *,
        lease: AgentRuntimeLease,
        previous_strategy_asset: dict[str, Any] | None,
    ) -> "SubmissionTriggerResult":
        """Spec 015 FR-003 / FR-004: check if there is any external new fact
        gating this submission. No hits → internal_reasoning_only=True.

        Signal sources:
        - new_mea_event : macro_event asset newer than prev strategy
        - price_breach  : |mark delta| > threshold since prev market snapshot
        - quant_flip    : any horizon direction flipped since prev forecast snapshot
        - risk_brake    : new risk_brake_event asset since prev
        - owner_push    : current pm_trigger_event.wake_source is manual/owner_push
        """
        hits: list[str] = []
        details: dict[str, Any] = {}

        # Cold start: no previous strategy at all → treat as non-hesitation.
        # The very first strategy a PM emits per environment is always
        # "external" (the PM is starting a book from nothing).
        if previous_strategy_asset is None:
            return SubmissionTriggerResult(
                internal_reasoning_only=False,
                hits=["cold_start"],
                details={"cold_start": True},
            )

        prev_payload = dict(previous_strategy_asset.get("payload") or {})
        prev_metadata = dict(previous_strategy_asset.get("metadata") or {})
        prev_generated_at = self._parse_utc_iso(prev_payload.get("generated_at_utc"))

        # 1) owner_push
        latest_pm_trigger_event = (
            dict(lease.pack.payload.get("latest_pm_trigger_event"))
            if isinstance(lease.pack.payload.get("latest_pm_trigger_event"), dict)
            else {}
        )
        wake_source = str(latest_pm_trigger_event.get("wake_source") or "").strip().lower()
        if wake_source in self._PM_SUBMIT_GATE_OWNER_WAKE_SOURCES:
            hits.append("owner_push")
            details["owner_push"] = {"wake_source": wake_source}

        # 2) new_mea_event
        if self.memory_assets is not None:
            recent_macro_events = self.memory_assets.recent_assets(asset_type="macro_event", limit=20)
            for asset in recent_macro_events:
                created_at = self._parse_utc_iso(asset.get("created_at"))
                if created_at is None:
                    continue
                if prev_generated_at is None or created_at > prev_generated_at:
                    hits.append("new_mea_event")
                    details["new_mea_event"] = {
                        "event_id": str(asset.get("asset_id") or ""),
                        "created_at": asset.get("created_at"),
                    }
                    break

        # 3) risk_brake
        if self.memory_assets is not None:
            recent_brakes = self.memory_assets.recent_assets(
                asset_type="risk_brake_event", actor_role="system", limit=5
            )
            for asset in recent_brakes:
                created_at = self._parse_utc_iso(asset.get("created_at"))
                if created_at is None:
                    continue
                if prev_generated_at is None or created_at > prev_generated_at:
                    hits.append("risk_brake")
                    details["risk_brake"] = {
                        "event_id": str(asset.get("asset_id") or ""),
                        "created_at": asset.get("created_at"),
                    }
                    break

        # 4) price_breach
        current_market_snapshot = self._snapshot_market_for_submit_gate(lease)
        prev_market_snapshot = dict(prev_metadata.get("submit_market_snapshot") or {})
        price_breach = self._detect_price_breach(
            prev_snapshot=prev_market_snapshot,
            current_snapshot=current_market_snapshot,
            threshold_pct=self._pm_submit_gate_price_breach_pct_threshold(),
        )
        if price_breach:
            hits.append("price_breach")
            details["price_breach"] = price_breach

        # 5) quant_flip
        current_forecast_snapshot = self._snapshot_forecasts_for_submit_gate(lease)
        prev_forecast_snapshot = dict(prev_metadata.get("submit_forecast_snapshot") or {})
        quant_flip = self._detect_quant_flip(
            prev_snapshot=prev_forecast_snapshot,
            current_snapshot=current_forecast_snapshot,
        )
        if quant_flip:
            hits.append("quant_flip")
            details["quant_flip"] = quant_flip

        return SubmissionTriggerResult(
            internal_reasoning_only=not hits,
            hits=hits,
            details=details,
        )

    def _pm_submit_gate_price_breach_pct_threshold(self) -> float:
        raw = getattr(
            self.policy_risk.settings.orchestrator if self.policy_risk is not None else None,
            "pm_submit_gate_price_breach_pct",
            None,
        )
        if raw is None:
            return self._PM_SUBMIT_GATE_PRICE_BREACH_PCT_DEFAULT
        try:
            return float(raw)
        except (TypeError, ValueError):
            return self._PM_SUBMIT_GATE_PRICE_BREACH_PCT_DEFAULT

    @staticmethod
    def _snapshot_market_for_submit_gate(lease: AgentRuntimeLease) -> dict[str, Any]:
        market = dict(lease.hidden_payload.get("market") or {})
        coin_markets = dict(market.get("market") or {})
        snapshot: dict[str, Any] = {"captured_at_utc": None, "coins": {}}
        captured_at = None
        for coin, entry in coin_markets.items():
            if not isinstance(entry, dict):
                continue
            mark_price_raw = entry.get("mark_price")
            try:
                mark_price = float(mark_price_raw) if mark_price_raw is not None else None
            except (TypeError, ValueError):
                mark_price = None
            coin_captured_at = entry.get("captured_at")
            if captured_at is None and coin_captured_at:
                captured_at = coin_captured_at
            snapshot["coins"][str(coin).upper()] = {
                "mark_price": mark_price,
                "captured_at": coin_captured_at,
            }
        snapshot["captured_at_utc"] = captured_at
        return snapshot

    @staticmethod
    def _snapshot_forecasts_for_submit_gate(lease: AgentRuntimeLease) -> dict[str, Any]:
        market_payload = dict(lease.pack.payload.get("market") or {})
        forecasts_payload = dict(lease.pack.payload.get("forecasts") or {})
        # pack.payload.forecasts is keyed by coin → {horizon: {direction/side/probability/...}}
        compact: dict[str, Any] = {}
        for coin, horizons in forecasts_payload.items():
            coin_key = str(coin).upper()
            if not isinstance(horizons, dict):
                continue
            compact[coin_key] = {}
            for horizon, data in horizons.items():
                if not isinstance(data, dict):
                    continue
                compact[coin_key][str(horizon)] = {
                    "direction": str(data.get("direction") or data.get("side") or "").lower() or None,
                    "confidence": data.get("confidence"),
                }
        return {
            "market_captured_at_utc": market_payload.get("market_captured_at_utc") or market_payload.get("captured_at"),
            "coins": compact,
        }

    @staticmethod
    def _detect_price_breach(
        *,
        prev_snapshot: dict[str, Any],
        current_snapshot: dict[str, Any],
        threshold_pct: float,
    ) -> dict[str, Any] | None:
        prev_coins = dict(prev_snapshot.get("coins") or {})
        current_coins = dict(current_snapshot.get("coins") or {})
        if not prev_coins or not current_coins:
            return None
        breaches: dict[str, float] = {}
        for coin, current_entry in current_coins.items():
            if not isinstance(current_entry, dict):
                continue
            prev_entry = prev_coins.get(coin)
            if not isinstance(prev_entry, dict):
                continue
            try:
                current_mark = float(current_entry.get("mark_price"))
                prev_mark = float(prev_entry.get("mark_price"))
            except (TypeError, ValueError):
                continue
            if prev_mark <= 0:
                continue
            pct = (current_mark - prev_mark) / prev_mark * 100.0
            if abs(pct) >= threshold_pct:
                breaches[coin] = round(pct, 3)
        if not breaches:
            return None
        return {"breaches_pct": breaches, "threshold_pct": threshold_pct}

    @staticmethod
    def _detect_quant_flip(
        *,
        prev_snapshot: dict[str, Any],
        current_snapshot: dict[str, Any],
    ) -> dict[str, Any] | None:
        prev_coins = dict(prev_snapshot.get("coins") or {})
        current_coins = dict(current_snapshot.get("coins") or {})
        if not prev_coins or not current_coins:
            return None
        flips: list[dict[str, Any]] = []
        for coin, current_horizons in current_coins.items():
            if not isinstance(current_horizons, dict):
                continue
            prev_horizons = prev_coins.get(coin) or {}
            for horizon, current_entry in current_horizons.items():
                current_direction = str((current_entry or {}).get("direction") or "").lower() or None
                prev_direction = str((prev_horizons.get(horizon) or {}).get("direction") or "").lower() or None
                if current_direction is None or prev_direction is None:
                    continue
                if current_direction == prev_direction:
                    continue
                # Treat flat → directional (or reverse) as a flip worth
                # surfacing, plus the obvious long ↔ short.
                flips.append(
                    {
                        "coin": coin,
                        "horizon": horizon,
                        "prev": prev_direction,
                        "current": current_direction,
                    }
                )
        if not flips:
            return None
        return {"flips": flips}

    def submit_execution(
        self,
        *,
        input_id: str,
        payload: dict[str, Any],
        live: bool | None = None,
        max_notional_usd: float | None = None,
    ) -> dict[str, Any]:
        lease = self._validate_runtime_lease(input_id=input_id, agent_role="risk_trader")
        # `live=None` means "caller didn't specify" — fall back to the
        # `execution_submit_defaults.live` we put on the runtime pack at
        # build time. Production packs default to live=True; tests that
        # build packs through the same harness inherit the same default.
        # An explicit live=False (e.g. dry-run from a script) is honored.
        # The broker's own `live_enabled` gate still applies downstream.
        if live is None:
            defaults = dict(lease.pack.payload.get("execution_submit_defaults") or {})
            live = bool(defaults.get("live", False))
        envelope = self.validate_submission(
            submission_kind="execution",
            agent_role="risk_trader",
            trace_id=lease.pack.trace_id,
            payload=payload,
        )
        submission = ExecutionSubmission.model_validate(envelope.payload)
        trigger_delta = dict(lease.pack.payload.get("trigger_delta") or {})
        if bool(trigger_delta.get("requires_tactical_map_refresh")) and submission.tactical_map_update is None:
            raise RuntimeInputLeaseError(
                reason="tactical_map_update_required",
                input_id=input_id,
                agent_role="risk_trader",
                detail=str(trigger_delta.get("tactical_map_refresh_reason") or "tactical_map_refresh_required"),
            )
        pending_entry_symbols = self._rt_pending_entry_symbols(lease)
        if submission.tactical_map_update is not None:
            missing_first_entry_symbols = self._missing_first_entry_plan_symbols(
                coin_updates=list(submission.tactical_map_update.coins),
                required_symbols=pending_entry_symbols,
            )
            if missing_first_entry_symbols:
                schema_ref, prompt_ref = self._submission_contract("execution")
                raise SubmissionValidationError(
                    schema_ref=schema_ref,
                    prompt_ref=prompt_ref,
                    errors=[
                        (
                            "tactical_map_update is incomplete for "
                            f"{', '.join(missing_first_entry_symbols)}: when PM has an active, unlocked target on "
                            "an unpositioned or wrong-way symbol, the map must say how the first bite gets placed. "
                            "Fill `first_entry_plan` for every pending symbol."
                        )
                    ],
                )
        if pending_entry_symbols and not self._execution_submission_covers_entry_gap(
            submission=submission,
            pending_entry_symbols=pending_entry_symbols,
        ):
            schema_ref, prompt_ref = self._submission_contract("execution")
            raise SubmissionValidationError(
                schema_ref=schema_ref,
                prompt_ref=prompt_ref,
                errors=[
                    (
                        "active entry gap detected for "
                        f"{', '.join(pending_entry_symbols)}: RT cannot keep submitting all-wait/no-entry batches "
                        "while these symbols are active, unlocked, and currently unpositioned. Either open/flip at "
                        "least one pending symbol now, or resubmit with root-level `pm_recheck_requested=true` plus "
                        "a non-empty `pm_recheck_reason`."
                    )
                ],
            )
        pm_recheck_reminder = self._build_rt_pm_recheck_reminder(submission)
        self._record_events(
            [
                self.build_submission_event(trace_id=lease.pack.trace_id, envelope=envelope),
                EventFactory.build(
                    trace_id=lease.pack.trace_id,
                    event_type="execution.submitted",
                    source_module="agent_gateway",
                    entity_type="execution_batch",
                    entity_id=submission.decision_id,
                    payload={
                        "execution": submission.model_dump(mode="json"),
                        "envelope_id": envelope.envelope_id,
                        "input_id": input_id,
                    },
                ),
                *(
                    [
                        EventFactory.build(
                            trace_id=lease.pack.trace_id,
                            event_type="agent.reminder.created",
                            source_module="agent_gateway",
                            entity_type="direct_reminder",
                            entity_id=pm_recheck_reminder.reminder_id,
                            payload=pm_recheck_reminder.model_dump(mode="json"),
                        )
                    ]
                    if pm_recheck_reminder is not None
                    else []
                ),
            ]
        )
        self.memory_assets.save_agent_session(
            agent_role="risk_trader",
            session_id=self.session_id_for_role("risk_trader"),
            last_task_kind="execution",
            last_submission_kind="execution",
        )
        if pm_recheck_reminder is not None:
            self.memory_assets.save_asset(
                asset_type="direct_reminder",
                payload=pm_recheck_reminder.model_dump(mode="json"),
                trace_id=lease.pack.trace_id,
                actor_role="risk_trader",
                group_key=pm_recheck_reminder.to_agent_role,
                source_ref=envelope.envelope_id,
                metadata={"decision_id": submission.decision_id, "input_id": input_id},
            )
        self.memory_assets.save_asset(
            asset_type="execution_batch",
            payload=submission.model_dump(mode="json"),
            trace_id=lease.pack.trace_id,
            actor_role="risk_trader",
            group_key=submission.decision_id,
            source_ref=envelope.envelope_id,
            metadata={"strategy_id": submission.strategy_id, "input_id": input_id},
        )
        strategy_key = self._strategy_key(
            dict(lease.hidden_payload.get("latest_strategy") or lease.pack.payload.get("strategy") or {})
        )
        current_lock_mode = self._rt_lock_mode_from_payload(lease.pack.payload)
        if submission.tactical_map_update is not None:
            self.memory_assets.materialize_rt_tactical_map(
                trace_id=lease.pack.trace_id,
                strategy_key=strategy_key,
                lock_mode=current_lock_mode,
                authored_payload=submission.tactical_map_update.model_dump(mode="json"),
                actor_role="risk_trader",
                source_ref=envelope.envelope_id,
                group_key=submission.decision_id,
                metadata={
                    "decision_id": submission.decision_id,
                    "strategy_id": submission.strategy_id,
                    "input_id": input_id,
                    "lock_mode": current_lock_mode,
                },
            )

        market = DataIngestBundle.model_validate(lease.hidden_payload.get("market") or {})
        policies = {
            coin: GuardDecision.model_validate(item)
            for coin, item in dict(lease.hidden_payload.get("policies") or {}).items()
        }
        strategy_payload = dict(lease.hidden_payload.get("latest_strategy") or lease.pack.payload.get("strategy") or {})
        context_by_symbol = {
            str(item.get("coin") or "").upper(): item
            for item in list(lease.pack.payload.get("execution_contexts") or [])
            if isinstance(item, dict)
        }
        decisions: list[ExecutionDecision] = []
        for item in submission.decisions:
            runtime_context = context_by_symbol.get(item.symbol, {})
            decisions.append(
                ExecutionDecision(
                    decision_id=submission.decision_id,
                    strategy_version=submission.strategy_id or "unknown",
                    context_id=str(runtime_context.get("context_id") or new_id("execctx")),
                    product_id=str(runtime_context.get("product_id") or f"{item.symbol}-PERP-INTX"),
                    coin=item.symbol,
                    action=item.action,
                    side=item.direction or ("flat" if item.action in {"wait", "hold"} else "long"),
                    size_pct_of_exposure_budget=item.size_pct_of_exposure_budget,
                    urgency=item.urgency,
                    valid_for_minutes=item.valid_for_minutes,
                    reason=item.reason,
                    priority=item.priority,
                )
            )

        authorization = self.policy_risk.authorize_execution(
            strategy_payload=strategy_payload,
            decisions=decisions,
            market=market,
            policies=policies,
        )
        self._record_events(
            self.policy_risk.build_execution_authorization_events(
                trace_id=lease.pack.trace_id,
                authorization=authorization,
            )
        )
        self.memory_assets.save_asset(
            asset_type="execution_authorization",
            payload=authorization.model_dump(mode="json"),
            trace_id=lease.pack.trace_id,
            actor_role="policy_risk",
            group_key=submission.decision_id,
            metadata={"strategy_id": submission.strategy_id, "input_id": input_id},
        )

        accepted = [ExecutionDecision.model_validate(item) for item in authorization.accepted]
        bounded_max_notional = float(max_notional_usd) if live and max_notional_usd is not None else None
        plans = self.trade_execution.build_execution_plans(
            decisions=accepted,
            total_equity_usd=market.portfolio.total_equity_usd,
            max_leverage=next(
                (
                    item.risk_limits.max_leverage
                    for item in policies.values()
                    if item.risk_limits.max_leverage
                ),
                1.0,
            ),
            max_notional_usd=bounded_max_notional,
        )
        self._record_events(self.trade_execution.build_plan_events(trace_id=lease.pack.trace_id, plans=plans))
        results = self.trade_execution.execute(plans, live=live)
        self._record_events(self.trade_execution.build_result_events(trace_id=lease.pack.trace_id, results=results))
        for result in results:
            self.memory_assets.save_asset(
                asset_type="execution_result",
                payload={"result_id": new_id("execution_result"), **result.model_dump(mode="json")},
                trace_id=lease.pack.trace_id,
                actor_role="risk_trader",
                group_key=submission.decision_id,
                metadata={"live": live, "input_id": input_id},
            )
        self._consume_runtime_lease(lease=lease, submission_kind="execution")
        return {
            "trace_id": lease.pack.trace_id,
            "input_id": input_id,
            "decision_id": submission.decision_id,
            "strategy_id": submission.strategy_id,
            "accepted_count": len(authorization.accepted),
            "rejected": authorization.rejected,
            "plan_count": len(plans),
            "execution_results": [item.model_dump(mode="json") for item in results],
            "live": bool(live),
        }

    @staticmethod
    def _rt_float_or_none(value: Any) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _rt_position_lock_mode(self, payload: dict[str, Any], symbol: str) -> str | None:
        latest_risk = dict(payload.get("latest_risk_brake_event") or {})
        position_locks = dict(latest_risk.get("position_locks") or {})
        if not position_locks:
            updates = dict(latest_risk.get("risk_lock_updates") or {})
            position_locks = dict(updates.get("position_locks") or {})
        mode = str(dict(position_locks.get(symbol) or {}).get("mode") or "").strip().lower()
        return mode or None

    def _rt_pending_entry_symbols(self, lease: AgentRuntimeLease) -> list[str]:
        global_lock_mode = str(self._rt_lock_mode_from_payload(lease.pack.payload) or "").strip().lower() or None
        if global_lock_mode in {"reduce_only", "flat_only"}:
            return []
        pending: list[str] = []
        for item in list(lease.pack.payload.get("execution_contexts") or []):
            if not isinstance(item, dict):
                continue
            target = dict(item.get("target") or {})
            symbol = str(target.get("symbol") or item.get("coin") or "").strip().upper()
            state = str(target.get("state") or "").strip().lower()
            direction = str(target.get("direction") or "").strip().lower()
            if not symbol or state != "active" or direction not in {"long", "short"}:
                continue
            if self._rt_position_lock_mode(lease.pack.payload, symbol) in {"reduce_only", "flat_only"}:
                continue
            account_snapshot = dict(item.get("account_snapshot") or {})
            current_side = str(account_snapshot.get("current_side") or "").strip().lower()
            current_notional = self._rt_float_or_none(account_snapshot.get("current_notional_usd"))
            if current_side == direction and current_notional is not None and abs(current_notional) > 0:
                continue
            pending.append(symbol)
        return sorted(dict.fromkeys(pending))

    @staticmethod
    def _execution_submission_covers_entry_gap(
        *,
        submission: ExecutionSubmission,
        pending_entry_symbols: list[str],
    ) -> bool:
        if submission.pm_recheck_requested:
            return True
        actionable_symbols = {
            str(item.symbol or "").strip().upper()
            for item in submission.decisions
            if item.action in {"open", "add", "flip"}
        }
        return bool(actionable_symbols.intersection({symbol.upper() for symbol in pending_entry_symbols}))

    @staticmethod
    def _build_rt_pm_recheck_reminder(submission: ExecutionSubmission) -> DirectAgentReminder | None:
        if not submission.pm_recheck_requested:
            return None
        reason = str(submission.pm_recheck_reason or "").strip()
        if not reason:
            return None
        return DirectAgentReminder(
            reminder_id=new_id("reminder"),
            from_agent_role="risk_trader",
            to_agent_role="pm",
            importance="high",
            message=reason,
        )

    def submit_news(
        self,
        *,
        input_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        lease = self._validate_runtime_lease(input_id=input_id, agent_role="macro_event_analyst")
        envelope = self.validate_submission(
            submission_kind="news",
            agent_role="macro_event_analyst",
            trace_id=lease.pack.trace_id,
            payload=payload,
        )
        submission = NewsSubmission.model_validate(envelope.payload)
        canonical_news = self.memory_assets.materialize_news_submission(
            trace_id=lease.pack.trace_id,
            authored_payload=submission.model_dump(mode="json"),
            actor_role="macro_event_analyst",
            source_ref=envelope.envelope_id,
        )
        self._record_events(
            [
                self.build_submission_event(trace_id=lease.pack.trace_id, envelope=envelope),
                EventFactory.build(
                    trace_id=lease.pack.trace_id,
                    event_type="news.submitted",
                    source_module="agent_gateway",
                    entity_type="news_submission",
                    entity_id=str(canonical_news["submission_id"]),
                    payload={
                        "news": canonical_news,
                        "envelope_id": envelope.envelope_id,
                        "input_id": input_id,
                    },
                ),
            ]
        )
        self.memory_assets.save_agent_session(
            agent_role="macro_event_analyst",
            session_id=self.session_id_for_role("macro_event_analyst"),
            last_task_kind="event_summary",
            last_submission_kind="news",
        )
        for item in canonical_news["events"]:
            event_id = str(item["event_id"])
            self.memory_assets.save_asset(
                asset_type="macro_event",
                payload=item,
                trace_id=lease.pack.trace_id,
                actor_role="macro_event_analyst",
                group_key=event_id,
                source_ref=str(canonical_news["submission_id"]),
                asset_id=f"macro_event:{event_id}",
            )
        self.memory_assets.save_asset(
            asset_type="macro_daily_memory",
            payload={
                "memory_day_utc": new_id("memory_day"),
                "summary": "; ".join(str(event["summary"]) for event in canonical_news["events"]),
                "event_ids": [str(event["event_id"]) for event in canonical_news["events"]],
            },
            trace_id=lease.pack.trace_id,
            actor_role="macro_event_analyst",
            group_key="macro_daily_memory",
            source_ref=envelope.envelope_id,
        )
        # Historical note: this flow used to auto-create DirectAgentReminder
        # assets for every high-impact news event. Nothing ever consumed those
        # assets — no runtime pack surfaced them, no monitor dispatched them
        # to PM/RT sessions. Removed 2026-04-17 so the only MEA→PM/RT wake
        # path is MEA's own skill-guided `sessions_send`, which the skill's
        # 必要性检查 段 now gates via the `your_recent_impact` harness panel.
        self._consume_runtime_lease(lease=lease, submission_kind="news")
        return {
            "trace_id": lease.pack.trace_id,
            "input_id": input_id,
            "submission_id": canonical_news["submission_id"],
            "macro_event_count": len(canonical_news["events"]),
            "high_impact_count": len([item for item in canonical_news["events"] if item["impact_level"] == "high"]),
        }

    def submit_retro(self, *, input_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        lease = self._validate_runtime_lease(input_id=input_id, agent_role="crypto_chief")
        legacy_fields = [
            field_name
            for field_name in ("meeting_id", "round_count", "transcript", "learning_completed", "learning_results")
            if field_name in dict(payload or {})
        ]
        if legacy_fields:
            raise SubmissionValidationError(
                schema_ref=self._CHIEF_RETRO_SPEC_REF,
                prompt_ref=self._CHIEF_RETRO_PROMPT_REF,
                errors=[f"legacy_field_forbidden:{field_name}" for field_name in legacy_fields],
                error_kind="retro_submit_legacy_fields_forbidden",
            )
        try:
            submission = RetroSubmission.model_validate(payload or {})
        except ValidationError as exc:
            owner_summary_missing = any(
                tuple(error.get("loc") or ()) == ("owner_summary",) and str(error.get("type") or "") == "missing"
                for error in exc.errors()
            )
            raise SubmissionValidationError(
                schema_ref=self._CHIEF_RETRO_SPEC_REF,
                prompt_ref=self._CHIEF_RETRO_PROMPT_REF,
                errors=["owner_summary_required"] if owner_summary_missing else ["invalid_retro_submit_payload"],
                error_kind="retro_submit_owner_summary_required" if owner_summary_missing else "retro_submit_invalid_payload",
            ) from exc
        owner_summary = str(submission.owner_summary or "").strip()
        if not owner_summary:
            raise SubmissionValidationError(
                schema_ref=self._CHIEF_RETRO_SPEC_REF,
                prompt_ref=self._CHIEF_RETRO_PROMPT_REF,
                errors=["owner_summary_required"],
                error_kind="retro_submit_owner_summary_required",
            )
        learning_targets = list(
            lease.pack.payload.get("learning_targets")
            or dict(lease.pack.payload.get("retro_pack") or {}).get("learning_targets")
            or self._capture_retro_learning_targets()
        )
        result = self._materialize_retro_outcome(
            trace_id=lease.pack.trace_id,
            input_id=input_id,
            payload=submission.model_dump(mode="json"),
            source_ref=input_id,
            learning_targets=learning_targets,
        )
        self._consume_runtime_lease(lease=lease, submission_kind="retro")
        return result

    def submit_retro_brief(self, *, input_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        lease = self._validate_retro_brief_lease(input_id=input_id)
        agent_role = lease.pack.agent_role
        retro_case = dict(lease.pack.payload.get("pending_retro_case") or {})
        case_id = str(retro_case.get("case_id") or "").strip()
        if not case_id:
            schema_ref, prompt_ref = self._retro_brief_contract_refs(agent_role)
            raise SubmissionValidationError(
                schema_ref=schema_ref,
                prompt_ref=prompt_ref,
                errors=["pending_retro_case_required"],
                error_kind="retro_brief_pending_case_required",
            )
        requested_case_id = str((payload or {}).get("case_id") or case_id).strip()
        if requested_case_id != case_id:
            schema_ref, prompt_ref = self._retro_brief_contract_refs(agent_role)
            raise SubmissionValidationError(
                schema_ref=schema_ref,
                prompt_ref=prompt_ref,
                errors=["retro_brief_case_mismatch"],
                error_kind="retro_brief_case_mismatch",
            )
        stored_case = self.memory_assets.get_retro_case(case_id=case_id)
        if stored_case is None:
            schema_ref, prompt_ref = self._retro_brief_contract_refs(agent_role)
            raise SubmissionValidationError(
                schema_ref=schema_ref,
                prompt_ref=prompt_ref,
                errors=["retro_case_not_found"],
                error_kind="retro_brief_case_not_found",
            )
        existing = self.memory_assets.latest_retro_brief(
            case_id=case_id,
            cycle_id=str(stored_case.get("cycle_id") or retro_case.get("cycle_id") or ""),
            agent_role=agent_role,
        )
        if existing is not None:
            schema_ref, prompt_ref = self._retro_brief_contract_refs(agent_role)
            raise SubmissionValidationError(
                schema_ref=schema_ref,
                prompt_ref=prompt_ref,
                errors=["retro_brief_already_submitted"],
                error_kind="retro_brief_already_submitted",
            )
        brief_submission = self._validate_retro_brief_submission(
            agent_role=agent_role,
            payload={
                **dict(payload or {}),
                "case_id": case_id,
            },
        )
        result = self._materialize_retro_brief_asset(
            trace_id=lease.pack.trace_id,
            agent_role=agent_role,
            retro_case=stored_case,
            brief_submission=brief_submission,
            source_ref=input_id,
        )
        self._consume_runtime_lease(lease=lease, submission_kind="retro_brief")
        return result

    def submit_macro_brief(
        self,
        *,
        input_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Chief's daily (or event-driven) macro brief submission — spec 014.

        Validates via MacroBriefSubmission; materializes as a `macro_brief`
        asset (immutable per NFR-004); drops no notification — consumers pick
        it up via runtime_pack on next pull.
        """
        lease = self._validate_runtime_lease(input_id=input_id, agent_role="crypto_chief")
        if str(lease.pack.task_kind or "") != "macro_brief":
            raise RuntimeInputLeaseError(
                reason="wrong_task_kind_for_macro_brief",
                input_id=input_id,
                agent_role="crypto_chief",
                detail=f"lease task_kind={lease.pack.task_kind!r}, expected macro_brief",
            )
        envelope = self.validate_submission(
            submission_kind="macro_brief",
            agent_role="crypto_chief",
            trace_id=lease.pack.trace_id,
            payload=payload,
        )
        prior_brief = dict(lease.pack.payload.get("prior_macro_brief") or {})
        prior_brief_id = str(prior_brief.get("brief_id") or "").strip() or None
        authored = dict(envelope.payload)
        prior_review = dict(authored.get("prior_brief_review") or {})
        submitted_prior_brief_id = str(prior_review.get("prior_brief_id") or "").strip()
        if prior_brief_id and submitted_prior_brief_id and submitted_prior_brief_id != prior_brief_id:
            schema_ref, prompt_ref = self._submission_contract("macro_brief")
            raise SubmissionValidationError(
                schema_ref=schema_ref,
                prompt_ref=prompt_ref,
                errors=[
                    f"prior_brief_id mismatch: submission refers to {submitted_prior_brief_id!r} "
                    f"but lease pack carried {prior_brief_id!r}"
                ],
                error_kind="macro_brief_prior_mismatch",
            )
        if not submitted_prior_brief_id and prior_brief_id:
            prior_review["prior_brief_id"] = prior_brief_id
            authored["prior_brief_review"] = prior_review
        canonical_brief = self.memory_assets.materialize_macro_brief(
            trace_id=lease.pack.trace_id,
            authored_payload=authored,
            actor_role="crypto_chief",
            source_ref=envelope.envelope_id,
            metadata={"input_id": input_id, "wake_mode": authored.get("wake_mode", "daily_macro_brief")},
        )
        self._record_events(
            [
                self.build_submission_event(trace_id=lease.pack.trace_id, envelope=envelope),
                EventFactory.build(
                    trace_id=lease.pack.trace_id,
                    event_type="macro_brief.submitted",
                    source_module="agent_gateway",
                    entity_type="macro_brief",
                    entity_id=str(canonical_brief.get("brief_id")),
                    payload={
                        "brief": canonical_brief,
                        "envelope_id": envelope.envelope_id,
                        "input_id": input_id,
                        "prior_brief_id": prior_brief_id,
                    },
                ),
            ]
        )
        self.memory_assets.save_agent_session(
            agent_role="crypto_chief",
            session_id=self.session_id_for_role("crypto_chief"),
            last_task_kind="macro_brief",
            last_submission_kind="macro_brief",
        )
        self._consume_runtime_lease(lease=lease, submission_kind="macro_brief")
        return {
            "trace_id": lease.pack.trace_id,
            "input_id": input_id,
            "brief_id": canonical_brief.get("brief_id"),
            "prior_brief_id": prior_brief_id,
            "verdict": (canonical_brief.get("prior_brief_review") or {}).get("verdict"),
        }

    # ------------------------------------------------------------------
    # Harness panels: "mirror" data shown to PM / MEA so they can gate
    # their own action on recent behavioral patterns instead of treating
    # every wake as a fresh blank-slate decision.
    # ------------------------------------------------------------------

    def _build_pm_since_last_strategy_panel(self) -> dict[str, Any]:
        """Surface 'what has materially changed since my last strategy?' data to PM.

        Purpose is harness-engineering: PM sees the deltas (MEA activity,
        RT executions, its own revision count today) BEFORE composing a
        new strategy. No action is blocked; the panel is read-only data
        meant to prompt the necessity question.
        """
        now = datetime.now(UTC)
        latest_strategy = (
            self.memory_assets.latest_asset(asset_type="strategy", actor_role="pm")
            or self.memory_assets.latest_asset(asset_type="strategy")
        )
        latest_created_at_raw = str((latest_strategy or {}).get("created_at") or "").strip()
        try:
            latest_created_at = datetime.fromisoformat(latest_created_at_raw.replace("Z", "+00:00")) if latest_created_at_raw else None
        except ValueError:
            latest_created_at = None
        elapsed_minutes = (
            int((now - latest_created_at).total_seconds() // 60) if latest_created_at is not None else None
        )

        cutoff_iso = latest_created_at.isoformat() if latest_created_at is not None else None
        today_utc = now.date().isoformat()

        # MEA submissions since last strategy
        mea_since = [
            asset
            for asset in self.memory_assets.recent_assets(asset_type="news_submission", limit=30)
            if cutoff_iso is None or str(asset.get("created_at") or "") > cutoff_iso
        ]
        impact_counter: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
        flip_trigger_impacting = 0
        for asset in mea_since:
            payload = dict(asset.get("payload") or {})
            for ev in payload.get("events") or []:
                if not isinstance(ev, dict):
                    continue
                impact = str(ev.get("impact") or "").lower().strip()
                if impact in impact_counter:
                    impact_counter[impact] += 1
                if str(ev.get("thesis_alignment") or "").lower().strip() == "flip_trigger":
                    flip_trigger_impacting += 1

        # RT executions since last strategy
        rt_executions_since = [
            asset
            for asset in self.memory_assets.recent_assets(asset_type="execution_batch", actor_role="risk_trader", limit=30)
            if cutoff_iso is None or str(asset.get("created_at") or "") > cutoff_iso
        ]

        # Your revision pattern today
        today_strategies = [
            asset
            for asset in self.memory_assets.recent_assets(asset_type="strategy", actor_role="pm", limit=40)
            if str(asset.get("created_at") or "").startswith(today_utc)
        ]
        revisions_today = len(today_strategies)
        # bandwidth oscillation: range of target_gross_exposure_band_pct lower/upper across today
        lowers: list[float] = []
        uppers: list[float] = []
        portfolio_modes: list[str] = []
        invalidation_triggered_today = 0
        for asset in today_strategies:
            p = dict(asset.get("payload") or {})
            band = p.get("target_gross_exposure_band_pct") or []
            if isinstance(band, list) and len(band) >= 2:
                try:
                    lowers.append(float(band[0]))
                    uppers.append(float(band[1]))
                except (TypeError, ValueError):
                    pass
            portfolio_modes.append(str(p.get("portfolio_mode") or ""))
            # crude heuristic: if metadata/trigger indicates invalidation, count it
            meta = asset.get("metadata") or {}
            trigger = str((meta.get("trigger_type") if isinstance(meta, dict) else "") or "").lower()
            if "invalidation" in trigger or "brake" in trigger or "risk" in trigger:
                invalidation_triggered_today += 1
        same_mode_count = (
            len({m for m in portfolio_modes if m}) == 1 and len(portfolio_modes) > 1
        )
        oscillation_pp: float | None = None
        if lowers and uppers:
            oscillation_pp = round(
                max(max(lowers) - min(lowers), max(uppers) - min(uppers)),
                2,
            )

        # Build the reflection hint — this is the natural-language mirror
        # PM reads BEFORE composing a new strategy.
        hint_parts: list[str] = []
        if latest_created_at is None:
            hint_parts.append("还没有任何策略历史，本次是首次提交。")
        else:
            hint_parts.append(
                f"距上一版策略 {elapsed_minutes} 分钟。"
                if elapsed_minutes is not None
                else "距上一版策略时间未知。"
            )
            hint_parts.append(
                f"期间 MEA 提交 {len(mea_since)} 条（其中 {flip_trigger_impacting} 条标注 flip_trigger 影响）。"
            )
            hint_parts.append(f"期间 RT 提交 {len(rt_executions_since)} 次执行批次。")
        if revisions_today >= 3:
            hint_parts.append(
                f"今天已经提交 {revisions_today} 版策略"
                + (f"，同组合模式 {portfolio_modes[0]}" if same_mode_count else "")
                + (f"，带宽震荡 {oscillation_pp}pp" if oscillation_pp is not None else "")
                + f"，invalidation 触发次数 {invalidation_triggered_today}。"
            )
        if (
            revisions_today >= 3
            and flip_trigger_impacting == 0
            and invalidation_triggered_today == 0
        ):
            hint_parts.append(
                "⚠ 今日多次修订均非 invalidation 触发且无 MEA flip_trigger 影响事件——"
                "先确认本次修订是新信号、还是继续微调；如果只是增量确认，考虑跳过本轮提交。"
            )

        return {
            "last_revision_id": str((latest_strategy or {}).get("payload", {}).get("strategy_id") or "") or None,
            "last_revision_at_utc": latest_created_at_raw or None,
            "elapsed_minutes_since_last_revision": elapsed_minutes,
            "mea_submissions_since": len(mea_since),
            "mea_submissions_by_impact": impact_counter,
            "mea_flip_trigger_impacting_since": flip_trigger_impacting,
            "rt_executions_since": len(rt_executions_since),
            "your_revisions_today": revisions_today,
            "your_portfolio_modes_today": portfolio_modes,
            "your_bandwidth_oscillation_pp_today": oscillation_pp,
            "invalidation_triggered_count_today": invalidation_triggered_today,
            "necessity_hint": " ".join(hint_parts) if hint_parts else "",
        }

    def _build_mea_recent_impact_panel(self) -> dict[str, Any]:
        """Surface 'how often have my submissions actually changed PM state?' data to MEA.

        Purpose is harness-engineering: MEA sees its own signal-to-action
        ratio BEFORE deciding to submit / sessions_send again. No submission
        is blocked.
        """
        now = datetime.now(UTC)
        since_cutoff = (now - timedelta(hours=24)).isoformat()

        recent_submissions = [
            asset
            for asset in self.memory_assets.recent_assets(asset_type="news_submission", limit=30)
            if str(asset.get("created_at") or "") >= since_cutoff
        ]
        category_counter: dict[str, int] = {}
        high_impact_events_past_24h = 0
        for asset in recent_submissions:
            for ev in dict(asset.get("payload") or {}).get("events") or []:
                if not isinstance(ev, dict):
                    continue
                cat = str(ev.get("category") or "uncategorized").strip().lower() or "uncategorized"
                category_counter[cat] = category_counter.get(cat, 0) + 1
                if str(ev.get("impact") or "").lower().strip() == "high":
                    high_impact_events_past_24h += 1

        recent_pm_strategies = [
            asset
            for asset in self.memory_assets.recent_assets(asset_type="strategy", actor_role="pm", limit=30)
            if str(asset.get("created_at") or "") >= since_cutoff
        ]
        pm_revisions_past_24h = len(recent_pm_strategies)

        # Theme fatigue: any category with >= 3 submissions in 24h AND fewer
        # PM revisions than submissions means the signal is being ignored / over-produced.
        fatigued_categories = sorted(
            [(cat, count) for cat, count in category_counter.items() if count >= 3],
            key=lambda pair: -pair[1],
        )

        hint_parts: list[str] = []
        hint_parts.append(
            f"过去 24h 你提交 {len(recent_submissions)} 份 news（含 {high_impact_events_past_24h} 条 high impact 事件）。"
        )
        hint_parts.append(f"同期 PM 提交 {pm_revisions_past_24h} 版策略。")
        if fatigued_categories:
            top_cat, top_count = fatigued_categories[0]
            hint_parts.append(
                f"⚠ category=`{top_cat}` 24h 内已出现 {top_count} 次。"
                "提交新条目前先问：这次是新事实还是同一叙事的补充报道？"
                "如果只是补充/措辞/二次来源，考虑合并为已有 composite event 的 status 更新，不单独成条。"
            )

        return {
            "submissions_past_24h": len(recent_submissions),
            "high_impact_events_past_24h": high_impact_events_past_24h,
            "submissions_by_category_past_24h": category_counter,
            "pm_revisions_past_24h": pm_revisions_past_24h,
            "theme_fatigue_candidates": [
                {"category": cat, "count": count} for cat, count in fatigued_categories
            ],
            "necessity_hint": " ".join(hint_parts),
        }

    def _issue_runtime_pack(
        self,
        *,
        agent_role: str,
        task_kind: str,
        trigger_type: str,
        params: dict[str, object] | None = None,
    ) -> AgentRuntimePack:
        self._require_runtime_bridge_dependencies()
        trace_id = new_id("trace")
        resolved_params = dict(params or {})
        latest_pm_trigger_event = None
        resolved_trigger_type = trigger_type
        if agent_role == "pm":
            resolved_trigger_type, resolved_params = self._normalize_pm_pull_request(
                trigger_type=trigger_type,
                params=resolved_params,
            )
            latest_pm_trigger_event = self.memory_assets.claim_pending_pm_trigger_event(claim_ref=trace_id)
            if latest_pm_trigger_event is not None:
                resolved_trigger_type = str(latest_pm_trigger_event.get("trigger_type") or resolved_trigger_type).strip() or resolved_trigger_type
            else:
                inherited_pm_trigger_event = self._inherit_recent_pm_message_trigger_event(
                    trigger_type=resolved_trigger_type,
                    params=resolved_params,
                )
                if inherited_pm_trigger_event is not None:
                    resolved_trigger_type = str(
                        inherited_pm_trigger_event.get("trigger_type") or resolved_trigger_type
                    ).strip() or resolved_trigger_type
                    resolved_params = inherited_pm_trigger_event
                latest_pm_trigger_event = self._record_pm_pull_trigger_event(
                    trace_id=trace_id,
                    trigger_type=resolved_trigger_type,
                    params=resolved_params,
                )
        trigger_context = self._build_trigger_context(
            agent_role=agent_role,
            trigger_type=resolved_trigger_type,
            params=resolved_params,
        )
        runtime_bundle = self._resolve_runtime_bridge_bundle(
            agent_role=agent_role,
            trace_id=trace_id,
            trigger_type=resolved_trigger_type,
        )
        context = dict(runtime_bundle["context"] or {})
        runtime_inputs = runtime_bundle["runtime_inputs"]
        snapshot_meta = dict(runtime_bundle.get("snapshot_meta") or {})
        runtime_input = runtime_inputs[agent_role]
        expires_at = datetime.now(UTC) + timedelta(seconds=self.runtime_pack_ttl_seconds)
        if agent_role == "crypto_chief" and task_kind == "macro_brief":
            chief_payload = runtime_inputs["crypto_chief"].payload
            prior_brief = self.memory_assets.latest_macro_brief() if self.memory_assets is not None else None
            recent_briefs = (
                self.memory_assets.recent_macro_briefs(limit=5) if self.memory_assets is not None else []
            )
            payload = {
                "macro_brief_pack": {
                    "market": chief_payload.get("market", {}),
                    "macro_prices": chief_payload.get("macro_prices", {}),
                    "news_events": chief_payload.get("news_events", []),
                    "macro_memory": chief_payload.get("macro_memory", []),
                    "forecasts": chief_payload.get("forecasts", {}),
                    "previous_strategy": chief_payload.get("previous_strategy", {}),
                    "digital_oracle": {
                        "preset": "chief_regime_read",
                        "wrapper": "/Users/chenzian/openclaw-trader/scripts/digital_oracle_query.py",
                    },
                },
                "prior_macro_brief": prior_brief,
                "recent_macro_briefs": recent_briefs,
                "trigger_context": trigger_context,
                "runtime_bridge_state": snapshot_meta,
                "pending_learning_directives": self._pending_learning_directives_payload("crypto_chief"),
            }
            hidden_payload: dict[str, Any] = {
                "runtime_inputs": {
                    role: item.model_dump(mode="json")
                    for role, item in runtime_inputs.items()
                }
            }
        elif agent_role == "crypto_chief":
            learning_targets = self._capture_retro_learning_targets()
            retro_cycle_state, retro_case = self._latest_runtime_retro_context()
            retro_briefs = self._prepared_retro_briefs(
                case_id=str(retro_case.get("case_id") or ""),
                cycle_id=str(retro_case.get("cycle_id") or retro_cycle_state.get("cycle_id") or ""),
            )
            pending_brief_roles = list(retro_cycle_state.get("missing_brief_roles") or [])
            if not pending_brief_roles:
                pending_brief_roles = [
                    role
                    for role in self._RETRO_BRIEF_ROLES
                    if role not in {str(item.get("agent_role") or "") for item in retro_briefs}
                ]
            payload = {
                "retro_pack": {
                    "market": runtime_inputs["crypto_chief"].payload.get("market", {}),
                    "risk_limits": runtime_inputs["crypto_chief"].payload.get("risk_limits", {}),
                    "forecasts": runtime_inputs["crypto_chief"].payload.get("forecasts", {}),
                    "strategy": runtime_inputs["crypto_chief"].payload.get("previous_strategy", {}),
                    "news_events": runtime_inputs["crypto_chief"].payload.get("news_events", []),
                    "execution_contexts": runtime_inputs["crypto_chief"].payload.get("execution_contexts", []),
                    "macro_memory": runtime_inputs["crypto_chief"].payload.get("macro_memory", []),
                    "recent_execution_results": self.memory_assets.get_recent_execution_results(limit=10),
                    "recent_news_submissions": self.memory_assets.get_recent_news_submissions(limit=10),
                    "learning_targets": learning_targets,
                },
                "retro_cycle_state": retro_cycle_state,
                "retro_case": retro_case,
                "retro_briefs": retro_briefs,
                "pending_retro_brief_roles": pending_brief_roles,
                "retro_briefs_ready": bool(retro_case) and not pending_brief_roles,
                "retro_ready_for_synthesis": bool(retro_case) and not pending_brief_roles,
                "pending_learning_directives": [
                    item
                    for item in self.memory_assets.get_learning_directives(
                        case_id=str(retro_case.get("case_id") or ""),
                        cycle_id=str(retro_case.get("cycle_id") or retro_cycle_state.get("cycle_id") or "") or None,
                    )
                    if str(item.get("completion_state") or "pending") == "pending"
                ]
                if retro_case
                else [],
                "learning_targets": learning_targets,
                "trigger_context": trigger_context,
                "runtime_bridge_state": snapshot_meta,
            }
            hidden_payload = {
                "runtime_inputs": {
                    role: item.model_dump(mode="json")
                    for role, item in runtime_inputs.items()
                }
            }
        else:
            payload = dict(runtime_input.payload)
            payload["trigger_context"] = trigger_context
            payload["runtime_bridge_state"] = snapshot_meta
            if latest_pm_trigger_event is not None and agent_role == "pm":
                payload["latest_pm_trigger_event"] = latest_pm_trigger_event
            latest_risk_brake_event = self._latest_risk_brake_event()
            if latest_risk_brake_event is not None and agent_role in {"pm", "risk_trader"}:
                payload["latest_risk_brake_event"] = latest_risk_brake_event
            if agent_role == "pm":
                # Harness "mirror": show PM its own recent behavior so it can
                # gate revision on necessity instead of treating every wake as
                # a fresh blank-slate decision. Read-only; blocks nothing.
                try:
                    payload["since_last_strategy"] = self._build_pm_since_last_strategy_panel()
                except Exception:  # noqa: BLE001
                    pass
            if agent_role == "macro_event_analyst":
                # Harness "mirror": show MEA its signal-to-action ratio so it
                # can filter noise before composing / notifying. Read-only.
                try:
                    payload["your_recent_impact"] = self._build_mea_recent_impact_panel()
                except Exception:  # noqa: BLE001
                    pass
            if agent_role == "risk_trader":
                payload["recent_execution_thoughts"] = self.memory_assets.get_recent_execution_thoughts(limit=5)
                latest_trigger_event = self._latest_rt_trigger_event()
                if latest_trigger_event is not None:
                    payload["latest_rt_trigger_event"] = latest_trigger_event
                strategy_key = self._strategy_key(dict(payload.get("strategy") or {}))
                lock_mode = self._rt_lock_mode_from_payload(payload)
                payload["standing_tactical_map"] = self._standing_rt_tactical_map(
                    payload=payload,
                    strategy_key=strategy_key,
                    lock_mode=lock_mode,
                )
                payload["trigger_delta"] = self._build_rt_trigger_delta(
                    payload=payload,
                    strategy_key=strategy_key,
                    lock_mode=lock_mode,
                )
                payload["execution_submit_defaults"] = {
                    "trigger_type": trigger_context.get("trigger_type"),
                    "live": True,
                }
                payload["runtime_bridge_state"] = {
                    **snapshot_meta,
                    "strategy_key": strategy_key,
                    "lock_mode": lock_mode,
                }
                payload["rt_decision_digest"] = self._build_rt_decision_digest(payload)
            if agent_role in self._RETRO_BRIEF_ROLES:
                payload.update(self._build_retro_brief_runtime_payload(agent_role))
            hidden_payload = {
                "market": context["market"],
                "policies": context["policies"],
                "forecasts": context["forecasts"],
                "news": context["news"],
                "latest_strategy": context["latest_strategy"] or {},
                "macro_memory": list(context["macro_memory"]),
            }
        pack = AgentRuntimePack(
            input_id=runtime_input.input_id,
            trace_id=trace_id,
            agent_role=agent_role,
            task_kind=task_kind,
            trigger_type=resolved_trigger_type,
            expires_at_utc=expires_at,
            payload=payload,
        )
        lease = AgentRuntimeLease(
            pack=pack,
            trigger_context=trigger_context,
            hidden_payload=hidden_payload,
        )
        self.memory_assets.save_agent_session(
            agent_role=agent_role,
            session_id=self.session_id_for_role(agent_role),
            last_task_kind=task_kind,
        )
        self.memory_assets.save_asset(
            asset_type="agent_runtime_lease",
            asset_id=pack.input_id,
            payload=lease.model_dump(mode="json"),
            trace_id=trace_id,
            actor_role="system",
            group_key=agent_role,
            metadata={
                "status": lease.status,
                "trigger_type": resolved_trigger_type,
                "expires_at_utc": expires_at.isoformat(),
            },
        )
        if self.trigger_bridge is not None:
            self.trigger_bridge.record_runtime_pack_issued(
                input_id=pack.input_id,
                trace_id=trace_id,
                agent_role=agent_role,
                trigger_context=trigger_context,
                expires_at_utc=expires_at.isoformat(),
            )
        return pack

    def _resolve_runtime_bridge_bundle(
        self,
        *,
        agent_role: str,
        trace_id: str,
        trigger_type: str,
    ) -> dict[str, Any]:
        max_age_seconds = self.runtime_bridge_max_age_seconds
        bridge_asset = self.memory_assets.get_runtime_bridge_state_asset(max_age_seconds=max_age_seconds)
        snapshot_source = "cache"
        if bridge_asset is None and self.runtime_bridge_monitor is not None:
            try:
                bridge_asset = self.runtime_bridge_monitor.refresh_once(
                    reason=f"pull:{agent_role}",
                    trace_id=trace_id,
                    force_sync_news=agent_role == "macro_event_analyst" and trigger_type == "news_batch_ready",
                )
            except Exception:
                bridge_asset = None
            if bridge_asset is None:
                stale_asset = self.memory_assets.latest_runtime_bridge_state_asset()
                if stale_asset is not None:
                    bridge_asset = stale_asset
                    snapshot_source = "stale_cache"
        elif bridge_asset is None:
            stale_asset = self.memory_assets.latest_runtime_bridge_state_asset()
            if stale_asset is not None:
                bridge_asset = stale_asset
                snapshot_source = "stale_cache"

        if bridge_asset is not None:
            payload = dict(bridge_asset.get("payload") or {})
            context = dict(payload.get("context") or {})
            runtime_inputs = self._runtime_inputs_from_bridge_state(
                trace_id=trace_id,
                base_runtime_inputs=dict(payload.get("runtime_inputs") or {}),
            )
            if runtime_inputs:
                if snapshot_source == "cache" and max_age_seconds is not None:
                    asset_age = self._runtime_bridge_asset_age_seconds(bridge_asset)
                    if asset_age is not None and asset_age > max_age_seconds:
                        snapshot_source = "stale_cache"
                return {
                    "context": context,
                    "runtime_inputs": runtime_inputs,
                    "snapshot_meta": self._runtime_bridge_snapshot_meta(bridge_asset, source=snapshot_source),
                }

        context_models = self._collect_bridge_context(
            agent_role=agent_role,
            trace_id=trace_id,
            trigger_type=trigger_type,
        )
        runtime_inputs = self.build_runtime_inputs(
            trace_id=trace_id,
            market=context_models["market"],
            policies=context_models["policies"],
            forecasts=context_models["forecasts"],
            news_events=context_models["news"],
            latest_strategy=context_models["latest_strategy"],
            macro_memory=context_models["macro_memory"],
        )
        return {
            "context": {
                "market": context_models["market"].model_dump(mode="json"),
                "policies": {coin: decision.model_dump(mode="json") for coin, decision in context_models["policies"].items()},
                "forecasts": {coin: forecast.model_dump(mode="json") for coin, forecast in context_models["forecasts"].items()},
                "news": [item.model_dump(mode="json") for item in context_models["news"]],
                "latest_strategy": context_models["latest_strategy"] or {},
                "macro_memory": list(context_models["macro_memory"]),
            },
            "runtime_inputs": runtime_inputs,
            "snapshot_meta": {
                "source": "direct_fallback",
                "refreshed_at_utc": datetime.now(UTC).isoformat(),
                "age_seconds": None,
            },
        }

    def _runtime_inputs_from_bridge_state(
        self,
        *,
        trace_id: str,
        base_runtime_inputs: dict[str, Any],
    ) -> dict[str, AgentRuntimeInput]:
        runtime_inputs: dict[str, AgentRuntimeInput] = {}
        for role, item in base_runtime_inputs.items():
            if not isinstance(item, dict):
                continue
            payload = copy.deepcopy(dict(item.get("payload") or {}))
            payload["trace_id"] = trace_id
            task_kind = str(item.get("task_kind") or self._task_kind_for_role(role))
            runtime_inputs[role] = AgentRuntimeInput(
                input_id=new_id("input"),
                agent_role=role,
                task_kind=task_kind,
                payload=payload,
            )
        return runtime_inputs

    @staticmethod
    def _task_kind_for_role(agent_role: str) -> str:
        mapping = {
            "pm": "strategy",
            "risk_trader": "execution",
            "macro_event_analyst": "event_summary",
            "crypto_chief": "retro",
        }
        return mapping.get(agent_role, "generic")

    @staticmethod
    def _runtime_bridge_asset_age_seconds(asset: dict[str, Any]) -> float | None:
        payload = dict(asset.get("payload") or {})
        raw_timestamp = payload.get("refreshed_at_utc") or asset.get("created_at")
        try:
            refreshed_at = datetime.fromisoformat(str(raw_timestamp).replace("Z", "+00:00"))
        except Exception:
            return None
        if refreshed_at.tzinfo is None:
            refreshed_at = refreshed_at.replace(tzinfo=UTC)
        return (datetime.now(UTC) - refreshed_at.astimezone(UTC)).total_seconds()

    def _runtime_bridge_snapshot_meta(self, asset: dict[str, Any], *, source: str) -> dict[str, Any]:
        payload = dict(asset.get("payload") or {})
        return {
            "source": source,
            "refreshed_at_utc": payload.get("refreshed_at_utc") or asset.get("created_at"),
            "age_seconds": self._runtime_bridge_asset_age_seconds(asset),
        }

    def _normalize_pm_pull_request(
        self,
        *,
        trigger_type: str,
        params: dict[str, object] | None = None,
    ) -> tuple[str, dict[str, object]]:
        payload = dict(params or {})
        raw_trigger_type = str(trigger_type or "").strip() or "pm_unspecified"
        normalized_trigger_type = self._PM_TRIGGER_TYPE_ALIASES.get(raw_trigger_type, raw_trigger_type)
        if normalized_trigger_type == "pm_main_cron":
            payload.setdefault("wake_source", "openclaw_cron")
            payload.setdefault("cadence_label", "pm-main")
            payload.setdefault("reason", "pm_main_cron")
        elif normalized_trigger_type == "agent_message":
            payload.setdefault("wake_source", "sessions_send")
            source_role = str(
                payload.get("source_role")
                or payload.get("sender_role")
                or payload.get("from_role")
                or payload.get("agent_role")
                or ""
            ).strip()
            if source_role:
                payload["source_role"] = source_role
            payload.setdefault("reason", payload.get("message_reason") or "agent_message")
        elif normalized_trigger_type == "manual":
            payload.setdefault("wake_source", "manual")
            payload.setdefault("reason", "manual")
        elif normalized_trigger_type in {"scheduled_recheck", "risk_brake"}:
            payload.setdefault("wake_source", "workflow_orchestrator")
            payload.setdefault("reason", normalized_trigger_type)
        else:
            normalized_trigger_type = "pm_unspecified"
            payload.setdefault("wake_source", "unknown")
            payload.setdefault("reason", "pm_unspecified")
        return normalized_trigger_type, payload

    def _record_pm_pull_trigger_event(
        self,
        *,
        trace_id: str,
        trigger_type: str,
        params: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        current = datetime.now(UTC)
        payload = dict(params or {})
        audit_origin = str(payload.get("audit_origin") or "agent_gateway_pull").strip() or "agent_gateway_pull"
        normalized = {
            "event_id": new_id("pm_trigger"),
            "detected_at_utc": current.isoformat(),
            "trigger_type": trigger_type,
            "trigger_category": self._PM_TRIGGER_CATEGORY_BY_TYPE.get(trigger_type, "unknown"),
            "reason": str(payload.get("reason") or trigger_type).strip() or trigger_type,
            "severity": str(payload.get("severity") or "normal").strip() or "normal",
            "wake_source": str(payload.get("wake_source") or "unknown").strip() or "unknown",
            "source_role": str(payload.get("source_role") or "").strip() or None,
            "source_session_key": str(payload.get("source_session_key") or "").strip() or None,
            "source_message_excerpt": str(payload.get("source_message_excerpt") or "").strip()[:240] or None,
            "cadence_label": str(payload.get("cadence_label") or "").strip() or None,
            "audit_origin": audit_origin,
            "inherited_from_event_id": str(payload.get("inherited_from_event_id") or "").strip() or None,
            "inherited_from_trace_id": str(payload.get("inherited_from_trace_id") or "").strip() or None,
            "claimable": False,
            "claimed_at_utc": current.isoformat(),
            "claimed_ref": trace_id,
            "dispatched": True,
        }
        self.memory_assets.save_asset(
            asset_type="pm_trigger_event",
            asset_id=str(normalized["event_id"]),
            payload=normalized,
            trace_id=trace_id,
            actor_role="system",
            group_key="pm",
            metadata={
                "trigger_type": trigger_type,
                "wake_source": normalized["wake_source"],
                "audit_origin": audit_origin,
            },
        )
        envelope = EventFactory.build(
            trace_id=trace_id,
            event_type=self._PM_TRIGGER_EVENT_TYPE,
            source_module="agent_gateway",
            entity_type="pm_trigger_event",
            entity_id=str(normalized["event_id"]),
            payload=normalized,
        )
        self.memory_assets.append_event(envelope)
        if self.event_bus is not None:
            try:
                self.event_bus.publish(envelope)
            except Exception:
                pass
        return normalized

    def _inherit_recent_pm_message_trigger_event(
        self,
        *,
        trigger_type: str,
        params: dict[str, object] | None,
    ) -> dict[str, object] | None:
        if trigger_type != "pm_unspecified":
            return None
        payload = dict(params or {})
        if not self._pm_pull_request_lacks_provenance(payload):
            return None
        recent_event = self.memory_assets.find_recent_pm_trigger_event(
            trigger_category="message",
            max_age_minutes=10,
        )
        if recent_event is None:
            return None
        return {
            "trigger_type": recent_event.get("trigger_type") or "agent_message",
            "wake_source": recent_event.get("wake_source"),
            "source_role": recent_event.get("source_role"),
            "source_session_key": recent_event.get("source_session_key"),
            "source_message_excerpt": recent_event.get("source_message_excerpt"),
            "reason": recent_event.get("reason"),
            "severity": recent_event.get("severity"),
            "audit_origin": "agent_gateway_pull_fallback_recent_message",
            "inherited_from_event_id": recent_event.get("event_id") or recent_event.get("asset_id"),
            "inherited_from_trace_id": recent_event.get("claimed_ref"),
        }

    @staticmethod
    def _pm_pull_request_lacks_provenance(params: dict[str, object]) -> bool:
        wake_source = str(params.get("wake_source") or "").strip()
        source_role = str(params.get("source_role") or params.get("sender_role") or params.get("from_role") or "").strip()
        source_session_key = str(params.get("source_session_key") or "").strip()
        reason = str(params.get("reason") or "").strip()
        if wake_source and wake_source != "unknown":
            return False
        if source_role or source_session_key:
            return False
        if reason and reason != "pm_unspecified":
            return False
        return True

    def _build_trigger_context(
        self,
        *,
        agent_role: str,
        trigger_type: str,
        params: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if self.trigger_bridge is None:
            return {
                "agent_role": agent_role,
                "trigger_type": trigger_type,
                "requested_at_utc": datetime.now(UTC).isoformat(),
                "metadata": dict(params or {}),
            }
        return self.trigger_bridge.get_trigger_context(
            agent_role=agent_role,
            trigger_type=trigger_type,
            params=params,
        )

    def _collect_bridge_context(
        self,
        *,
        agent_role: str,
        trace_id: str,
        trigger_type: str,
    ) -> dict[str, Any]:
        force_sync_news = agent_role == "macro_event_analyst" and trigger_type == "news_batch_ready"
        market = self.market_data.get_market_overview(trace_id=trace_id)
        self._persist_runtime_bridge_portfolio(
            trace_id=trace_id,
            agent_role=agent_role,
            trigger_type=trigger_type,
            market=market,
        )
        news = self.news_events.get_latest_news_batch(force_sync=force_sync_news)
        forecasts = self.quant_intelligence.get_latest_forecasts(market)
        latest_strategy_asset = self.memory_assets.get_latest_strategy()
        latest_strategy = latest_strategy_asset["payload"] if latest_strategy_asset and "payload" in latest_strategy_asset else latest_strategy_asset
        prior_risk_state = self.memory_assets.get_asset("risk_brake_state")
        policies = self.policy_risk.evaluate(
            market=market,
            forecasts=forecasts,
            news_events=news,
            prior_risk_state=dict((prior_risk_state or {}).get("payload") or {}),
            latest_strategy=latest_strategy or {},
        )
        macro_memory = self.memory_assets.get_macro_memory()
        return {
            "market": market,
            "news": news,
            "forecasts": forecasts,
            "policies": policies,
            "latest_strategy": latest_strategy,
            "macro_memory": macro_memory,
        }

    def _persist_runtime_bridge_portfolio(
        self,
        *,
        trace_id: str,
        agent_role: str,
        trigger_type: str,
        market: DataIngestBundle,
    ) -> None:
        portfolio_payload = market.portfolio.model_dump(mode="json")
        self.memory_assets.save_portfolio(trace_id, portfolio_payload)
        self.memory_assets.save_asset(
            asset_type="portfolio_snapshot",
            payload=portfolio_payload,
            trace_id=trace_id,
            actor_role="system",
            group_key=trace_id,
            metadata={
                "reason": "runtime_bridge_pull",
                "agent_role": agent_role,
                "trigger_type": trigger_type,
            },
        )

    def _require_runtime_bridge_dependencies(self) -> None:
        missing = [
            name
            for name, value in (
                ("memory_assets", self.memory_assets),
                ("market_data", self.market_data),
                ("news_events", self.news_events),
                ("quant_intelligence", self.quant_intelligence),
                ("policy_risk", self.policy_risk),
                ("trade_execution", self.trade_execution),
                ("notification_service", self.notification_service),
            )
            if value is None
        ]
        if missing:
            raise RuntimeError(f"agent_runtime_bridge_not_configured:{','.join(missing)}")

    def _validate_runtime_lease(self, *, input_id: str, agent_role: str) -> AgentRuntimeLease:
        self._require_runtime_bridge_dependencies()
        asset = self.memory_assets.get_asset(input_id)
        if asset is None or asset.get("asset_type") != "agent_runtime_lease":
            raise RuntimeInputLeaseError(reason="unknown_input_id", input_id=input_id, agent_role=agent_role)
        lease = AgentRuntimeLease.model_validate(asset.get("payload") or {})
        if lease.pack.agent_role != agent_role:
            raise RuntimeInputLeaseError(
                reason="wrong_agent_role",
                input_id=input_id,
                agent_role=agent_role,
                detail=str(lease.pack.agent_role),
            )
        if lease.status == "consumed" or lease.consumed_at_utc is not None:
            raise RuntimeInputLeaseError(reason="input_already_consumed", input_id=input_id, agent_role=agent_role)
        if lease.pack.expires_at_utc < datetime.now(UTC):
            raise RuntimeInputLeaseError(reason="input_expired", input_id=input_id, agent_role=agent_role)
        return lease

    def _consume_runtime_lease(self, *, lease: AgentRuntimeLease, submission_kind: str) -> None:
        updated = lease.model_copy(update={"status": "consumed", "consumed_at_utc": datetime.now(UTC)})
        self.memory_assets.save_asset(
            asset_type="agent_runtime_lease",
            asset_id=lease.pack.input_id,
            payload=updated.model_dump(mode="json"),
            trace_id=lease.pack.trace_id,
            actor_role="system",
            group_key=lease.pack.agent_role,
            metadata={
                "status": "consumed",
                "trigger_type": lease.pack.trigger_type,
                "expires_at_utc": lease.pack.expires_at_utc.isoformat(),
                "submission_kind": submission_kind,
            },
        )
        if self.trigger_bridge is not None:
            self.trigger_bridge.record_runtime_pack_consumed(
                input_id=lease.pack.input_id,
                trace_id=lease.pack.trace_id,
                agent_role=lease.pack.agent_role,
                submission_kind=submission_kind,
            )

    def _record_events(self, events) -> None:
        pending = list(events)
        while pending:
            event = pending.pop(0)
            self.memory_assets.append_event(event)
            self._publish_best_effort(event)
            if self.notification_service is not None:
                pending.extend(self.notification_service.handle_event(event))

    def _publish_best_effort(self, event) -> None:
        if self.event_bus is None:
            return None
        try:
            self.event_bus.publish(event)
        except Exception:
            return None

    def _latest_rt_trigger_event(self, *, max_age_minutes: int = 30) -> dict[str, Any] | None:
        asset = self.memory_assets.latest_asset(asset_type="rt_trigger_event", actor_role="system")
        if asset is None:
            return None
        payload = dict(asset.get("payload") or {})
        raw_timestamp = payload.get("detected_at_utc") or asset.get("created_at")
        try:
            detected_at = datetime.fromisoformat(str(raw_timestamp).replace("Z", "+00:00"))
        except Exception:
            detected_at = None
        if detected_at is not None:
            if detected_at.tzinfo is None:
                detected_at = detected_at.replace(tzinfo=UTC)
            if datetime.now(UTC) - detected_at.astimezone(UTC) > timedelta(minutes=max_age_minutes):
                return None
        fields = (
            "detected_at_utc",
            "reason",
            "severity",
            "coins",
            "cooldown_key",
            "bypass_cooldown",
            "metrics",
            "source_asset_ids",
            "dispatched",
            "skipped_reason",
            "cron_running",
        )
        return {
            "created_at": asset.get("created_at"),
            **{key: payload.get(key) for key in fields if key in payload},
        }

    def _latest_risk_brake_event(self, *, max_age_minutes: int = 120) -> dict[str, Any] | None:
        asset = self.memory_assets.latest_asset(asset_type="risk_brake_event", actor_role="system")
        if asset is None:
            return None
        payload = dict(asset.get("payload") or {})
        raw_timestamp = payload.get("detected_at_utc") or asset.get("created_at")
        try:
            detected_at = datetime.fromisoformat(str(raw_timestamp).replace("Z", "+00:00"))
        except Exception:
            detected_at = None
        if detected_at is not None:
            if detected_at.tzinfo is None:
                detected_at = detected_at.replace(tzinfo=UTC)
            if datetime.now(UTC) - detected_at.astimezone(UTC) > timedelta(minutes=max_age_minutes):
                return None
        fields = (
            "detected_at_utc",
            "scope",
            "state",
            "coins",
            "lock_mode",
            "portfolio_risk_state",
            "position_risk_state_by_coin",
            "rt_dispatched",
            "rt_skip_reason",
            "pm_dispatched",
            "pm_skip_reason",
            "system_decision_id",
            "execution_result_ids",
        )
        response = {
            "created_at": asset.get("created_at"),
            **{key: payload.get(key) for key in fields if key in payload},
        }
        if not response.get("lock_mode"):
            state_name = str(response.get("state") or "").strip().lower()
            if state_name == "reduce":
                response["lock_mode"] = "reduce_only"
            elif state_name == "exit":
                response["lock_mode"] = "flat_only"
        # Reconcile the (immutable) event record against the live
        # `risk_brake_state` asset. The event is a historical snapshot:
        # once a PM strategy revision releases the lock via
        # _release_locks_for_strategy, the event's lock_mode/state would
        # otherwise keep broadcasting reduce_only to RT for the full
        # 120-minute window, causing RT→PM→RT loops (observed 11:13-11:17).
        return self._reconcile_risk_brake_event_lock_status(response)

    def _reconcile_risk_brake_event_lock_status(
        self, response: dict[str, Any]
    ) -> dict[str, Any]:
        scope = str(response.get("scope") or "").strip().lower()
        event_lock_mode = str(response.get("lock_mode") or "").strip().lower() or None
        if event_lock_mode not in {"reduce_only", "flat_only"}:
            response["lock_status"] = "none"
            return response
        try:
            state_asset = self.memory_assets.get_asset("risk_brake_state")
        except Exception:
            state_asset = None
        if state_asset is None:
            response["lock_status"] = "unknown"
            return response
        state_payload = dict(state_asset.get("payload") or {})
        still_locked = False
        if scope == "portfolio":
            portfolio_lock = dict(state_payload.get("portfolio_lock") or {})
            still_locked = bool(portfolio_lock.get("mode"))
        elif scope == "position":
            position_locks = {
                str(k).upper(): dict(v or {})
                for k, v in (state_payload.get("position_locks") or {}).items()
            }
            event_coins = [str(c or "").upper() for c in (response.get("coins") or [])]
            active = [c for c in event_coins if position_locks.get(c, {}).get("mode")]
            if active:
                response["active_locks_by_coin"] = active
            still_locked = bool(active)
        else:
            response["lock_status"] = "unknown"
            return response
        if still_locked:
            response["lock_status"] = "active"
            return response
        response["lock_status"] = "released"
        response["lock_mode"] = None
        response["released_at_utc"] = state_payload.get("last_scan_at_utc")
        # Shadow the historical state label with "released" so decision
        # digests don't keep showing `reduce`/`exit` after the lock lifted.
        response["effective_state"] = "released"
        return response

    def _build_rt_decision_digest(self, payload: dict[str, Any]) -> dict[str, Any]:
        market = dict(payload.get("market") or {})
        portfolio = dict(market.get("portfolio") or {})
        strategy = dict(payload.get("strategy") or {})
        trigger_context = dict(payload.get("trigger_context") or {})
        latest_trigger_event = dict(payload.get("latest_rt_trigger_event") or {})
        latest_risk_brake_event = dict(payload.get("latest_risk_brake_event") or {})
        market_context = dict(market.get("market_context") or {})
        execution_contexts = list(payload.get("execution_contexts") or [])
        recent_thoughts = list(payload.get("recent_execution_thoughts") or [])
        news_events = list(payload.get("news_events") or [])

        lock_mode = self._rt_lock_mode_from_payload(payload)
        positions = list(portfolio.get("positions") or [])
        position_count = len(positions)
        focus_symbols: list[dict[str, Any]] = []
        for item in execution_contexts[:3]:
            if not isinstance(item, dict):
                continue
            coin = str(item.get("coin") or "").upper()
            target = dict(item.get("target") or {})
            account_snapshot = dict(item.get("account_snapshot") or {})
            market_snapshot = dict(item.get("market_snapshot") or {})
            context_snapshot = dict(market_context.get(coin) or {})
            focus_symbols.append(
                {
                    "coin": coin,
                    "target_state": target.get("state"),
                    "target_direction": target.get("direction"),
                    "target_exposure_band_pct": list(target.get("target_exposure_band_pct") or []),
                    "rt_discretion_band_pct": target.get("rt_discretion_band_pct"),
                    "current_side": account_snapshot.get("current_side"),
                    "current_notional_usd": account_snapshot.get("current_notional_usd"),
                    "current_position_share_pct_of_exposure_budget": item.get(
                        "current_position_share_pct_of_exposure_budget"
                    ),
                    "mark_price": market_snapshot.get("mark_price"),
                    "day_price_change_pct": market_snapshot.get("day_price_change_pct"),
                    "breakout_retest_state": context_snapshot.get("breakout_retest_state"),
                    "volatility_state": context_snapshot.get("volatility_state"),
                    "shape_summary": self._truncate_retro_text(
                        str(context_snapshot.get("shape_summary") or ""),
                        140,
                    ),
                    "execution_summary": dict(item.get("execution_summary") or {}),
                }
            )

        compact_thoughts: list[dict[str, Any]] = []
        for item in recent_thoughts[:3]:
            if not isinstance(item, dict):
                continue
            result = dict(item.get("execution_result") or {})
            compact_thoughts.append(
                {
                    "generated_at_utc": item.get("generated_at_utc"),
                    "symbol": item.get("symbol"),
                    "action": item.get("action"),
                    "direction": item.get("direction"),
                    "size_pct_of_exposure_budget": item.get("size_pct_of_exposure_budget"),
                    "reason": self._truncate_retro_text(str(item.get("reason") or ""), 120),
                    "reference_take_profit_condition": self._truncate_retro_text(
                        str(item.get("reference_take_profit_condition") or ""),
                        120,
                    ),
                    "reference_stop_loss_condition": self._truncate_retro_text(
                        str(item.get("reference_stop_loss_condition") or ""),
                        120,
                    ),
                    "execution_result": {
                        "status": result.get("status"),
                        "notional_usd": result.get("notional_usd"),
                        "executed_at_utc": result.get("executed_at_utc"),
                        "fills_count": result.get("fills_count"),
                    },
                }
            )

        compact_news = [
            {
                "title": self._truncate_retro_text(str(item.get("title") or ""), 120),
                "summary": self._truncate_retro_text(str(item.get("summary") or ""), 140),
                "severity": item.get("severity"),
                "published_at": item.get("published_at"),
            }
            for item in news_events[:3]
            if isinstance(item, dict)
        ]

        return {
            "instruction": "Read this digest first. Drill into execution_contexts, market.market_context, or recent_execution_thoughts only if the digest leaves ambiguity.",
            "read_order": [
                "trigger_summary",
                "portfolio_summary",
                "strategy_summary",
                "focus_symbols",
                "recent_memory",
            ],
            "trigger_summary": {
                "trigger_type": trigger_context.get("trigger_type"),
                "trigger_reason": latest_trigger_event.get("reason"),
                "trigger_severity": latest_trigger_event.get("severity"),
                "risk_brake_state": (
                    latest_risk_brake_event.get("effective_state")
                    or latest_risk_brake_event.get("state")
                ),
                "risk_brake_scope": latest_risk_brake_event.get("scope"),
                "risk_brake_lock_status": latest_risk_brake_event.get("lock_status"),
                "risk_lock_mode": lock_mode,
                "coins": list(latest_trigger_event.get("coins") or latest_risk_brake_event.get("coins") or []),
            },
            "portfolio_summary": {
                "captured_at": portfolio.get("captured_at"),
                "total_equity_usd": portfolio.get("total_equity_usd"),
                "available_equity_usd": portfolio.get("available_equity_usd"),
                "total_exposure_usd": portfolio.get("total_exposure_usd"),
                "position_count": position_count,
                "open_positions": [
                    {
                        "coin": item.get("coin"),
                        "side": item.get("side"),
                        "notional_usd": item.get("notional_usd"),
                        "position_share_pct_of_exposure_budget": item.get(
                            "position_share_pct_of_exposure_budget"
                        ),
                        "unrealized_pnl_usd": item.get("unrealized_pnl_usd"),
                    }
                    for item in positions[:3]
                    if isinstance(item, dict)
                ],
            },
            "strategy_summary": {
                "strategy_version": strategy.get("strategy_version"),
                "revision_number": strategy.get("revision_number"),
                "portfolio_mode": strategy.get("portfolio_mode"),
                "target_gross_exposure_band_pct": list(strategy.get("target_gross_exposure_band_pct") or []),
                "change_summary": self._truncate_retro_text(str(strategy.get("change_summary") or ""), 180),
                "flip_triggers": self._truncate_retro_text(str(strategy.get("flip_triggers") or ""), 180),
                "portfolio_invalidation": self._truncate_retro_text(
                    str(strategy.get("portfolio_invalidation") or ""),
                    160,
                ),
            },
            "focus_symbols": focus_symbols,
            "recent_memory": {
                "recent_execution_thoughts": compact_thoughts,
                "headline_risk": compact_news,
            },
        }

    def _standing_rt_tactical_map(
        self,
        *,
        payload: dict[str, Any],
        strategy_key: str,
        lock_mode: str | None,
    ) -> dict[str, Any] | None:
        asset = self.memory_assets.latest_rt_tactical_map(
            strategy_key=strategy_key,
            lock_mode=lock_mode,
            require_coins=True,
        )
        if asset is None:
            return None
        payload_data = dict(asset.get("payload") or {})
        if self._missing_first_entry_plan_symbols(
            coin_updates=list(payload_data.get("coins") or []),
            required_symbols=self._rt_pending_entry_symbols_from_payload(payload),
        ):
            return None
        return {
            "map_id": payload_data.get("map_id") or asset.get("asset_id"),
            **payload_data,
        }

    def _build_rt_trigger_delta(
        self,
        *,
        payload: dict[str, Any],
        strategy_key: str,
        lock_mode: str | None,
    ) -> dict[str, Any]:
        latest_trigger_event = dict(payload.get("latest_rt_trigger_event") or {})
        latest_risk_brake_event = dict(payload.get("latest_risk_brake_event") or {})
        latest_map_asset = self.memory_assets.latest_asset(asset_type="rt_tactical_map", actor_role="risk_trader")
        latest_map_payload = dict((latest_map_asset or {}).get("payload") or {})
        compatible_map_asset = self.memory_assets.latest_rt_tactical_map(
            strategy_key=strategy_key,
            lock_mode=lock_mode,
            require_coins=True,
        )
        compatible_map_payload = dict((compatible_map_asset or {}).get("payload") or {})
        pending_entry_symbols = self._rt_pending_entry_symbols_from_payload(payload)
        missing_first_entry_plan_symbols = (
            self._missing_first_entry_plan_symbols(
                coin_updates=list(compatible_map_payload.get("coins") or []),
                required_symbols=pending_entry_symbols,
            )
            if compatible_map_asset is not None
            else []
        )
        compatible_map_exists = compatible_map_asset is not None and not missing_first_entry_plan_symbols
        latest_map_strategy_key = str(latest_map_payload.get("strategy_key") or "").strip()
        latest_map_lock_mode = str(latest_map_payload.get("lock_mode") or "").strip() or None
        trigger_reason = str(latest_trigger_event.get("reason") or "").strip()
        trigger_severity = str(latest_trigger_event.get("severity") or "").strip() or None
        strategy_changed = bool(strategy_key and strategy_key != latest_map_strategy_key)
        risk_lock_changed = lock_mode != latest_map_lock_mode
        execution_changed = trigger_reason == "execution_followup"
        headline_risk_changed = bool(trigger_severity in {"high", "critical"})
        market_structure_changed_coins = list(latest_trigger_event.get("coins") or [])
        requires_tactical_map_refresh = False
        refresh_reason: str | None = None
        if not compatible_map_exists:
            if missing_first_entry_plan_symbols:
                requires_tactical_map_refresh = True
                refresh_reason = "active_target_missing_first_entry_plan"
            elif strategy_changed:
                requires_tactical_map_refresh = True
                refresh_reason = "pm_strategy_revision"
            elif risk_lock_changed and lock_mode is not None:
                requires_tactical_map_refresh = True
                refresh_reason = "risk_lock_changed"
            elif execution_changed:
                requires_tactical_map_refresh = True
                refresh_reason = "execution_followup"
            elif trigger_reason in {"pm_strategy_update", "risk_brake", "market_structure_change"}:
                requires_tactical_map_refresh = True
                refresh_reason = trigger_reason

        if compatible_map_exists:
            map_status = "compatible"
        elif latest_map_asset is None:
            map_status = "missing"
        elif missing_first_entry_plan_symbols:
            map_status = "missing_first_entry_plan"
        elif latest_map_strategy_key and latest_map_strategy_key != strategy_key:
            map_status = "stale_strategy"
        elif latest_map_lock_mode != lock_mode:
            map_status = "stale_lock_mode"
        else:
            map_status = "empty"

        return {
            "trigger_reason": trigger_reason or None,
            "trigger_severity": trigger_severity,
            "strategy_changed": strategy_changed,
            "risk_lock_changed": risk_lock_changed,
            "execution_changed": execution_changed,
            "market_structure_changed_coins": market_structure_changed_coins,
            "headline_risk_changed": headline_risk_changed,
            "lock_mode": lock_mode,
            "map_status": map_status,
            "requires_tactical_map_refresh": requires_tactical_map_refresh,
            "tactical_map_refresh_reason": refresh_reason,
            "missing_first_entry_plan_symbols": missing_first_entry_plan_symbols,
            "latest_tactical_map_strategy_key": latest_map_strategy_key or None,
            "latest_tactical_map_lock_mode": latest_map_lock_mode,
        }

    @staticmethod
    def _strategy_key(payload: dict[str, Any] | None) -> str:
        data = dict(payload or {})
        strategy_id = str(data.get("strategy_id") or "").strip()
        revision = str(data.get("revision_number") or "").strip()
        if strategy_id or revision:
            return f"{strategy_id}:{revision}"
        return ""

    @staticmethod
    def _rt_lock_mode_from_payload(payload: dict[str, Any]) -> str | None:
        precedence = {"normal": 0, "reduce_only": 1, "flat_only": 2}
        strongest: str | None = None
        latest_risk_brake_event = dict(payload.get("latest_risk_brake_event") or {})
        event_lock_mode = str(latest_risk_brake_event.get("lock_mode") or "").strip() or None
        if event_lock_mode in precedence:
            strongest = event_lock_mode
        for item in dict(payload.get("risk_limits") or {}).values():
            if not isinstance(item, dict):
                continue
            for candidate in (
                dict(item.get("portfolio_risk_state") or {}).get("lock_mode"),
                dict(item.get("position_risk_state") or {}).get("lock_mode"),
            ):
                mode = str(candidate or "").strip() or None
                if mode not in precedence:
                    continue
                if strongest is None or precedence[mode] > precedence.get(strongest, -1):
                    strongest = mode
        return strongest

    @staticmethod
    def _missing_first_entry_plan_symbols(
        *,
        coin_updates: list[Any],
        required_symbols: list[str],
    ) -> list[str]:
        required = [str(symbol or "").strip().upper() for symbol in required_symbols if str(symbol or "").strip()]
        if not required:
            return []
        coin_index: dict[str, dict[str, Any]] = {}
        for item in coin_updates:
            if hasattr(item, "model_dump"):
                raw = item.model_dump(mode="json")
            elif isinstance(item, dict):
                raw = dict(item)
            else:
                continue
            coin = str(raw.get("coin") or "").strip().upper()
            if coin:
                coin_index[coin] = raw
        missing: list[str] = []
        for symbol in required:
            item = coin_index.get(symbol)
            plan = str((item or {}).get("first_entry_plan") or "").strip()
            if not plan:
                missing.append(symbol)
        return missing

    def _rt_pending_entry_symbols_from_payload(self, payload: dict[str, Any]) -> list[str]:
        hidden_payload = {
            "execution_contexts": list(payload.get("execution_contexts") or []),
            "risk_limits": dict(payload.get("risk_limits") or {}),
            "latest_risk_brake_event": dict(payload.get("latest_risk_brake_event") or {}),
        }
        lease = AgentRuntimeLease(
            pack=AgentRuntimePack(
                input_id="synthetic-rt-pack",
                trace_id=str(payload.get("trace_id") or "trace-synthetic"),
                agent_role="risk_trader",
                task_kind="execution",
                trigger_type=str(dict(payload.get("trigger_context") or {}).get("trigger_type") or "condition_trigger"),
                expires_at_utc=datetime.now(UTC),
                payload=hidden_payload,
            ),
        )
        return self._rt_pending_entry_symbols(lease)


    def build_runtime_inputs(
        self,
        *,
        trace_id: str,
        market: DataIngestBundle,
        policies: dict[str, GuardDecision],
        forecasts: dict[str, CoinForecast],
        news_events: list[NewsDigestEvent],
        strategy: Any | None = None,
        execution_contexts: list[Any] | None = None,
        latest_strategy: dict | None = None,
        macro_memory: list[dict] | None = None,
        macro_snapshot: Any | None = None,
    ) -> dict[str, AgentRuntimeInput]:
        strategy_payload = latest_strategy["payload"] if latest_strategy and "payload" in latest_strategy else latest_strategy
        if strategy_payload is None and strategy is not None:
            strategy_payload = strategy.model_dump(mode="json") if hasattr(strategy, "model_dump") else dict(strategy)
        rt_strategy_payload = self._compact_strategy_payload(strategy_payload, agent_role="risk_trader")
        chief_strategy_payload = self._compact_strategy_payload(strategy_payload, agent_role="crypto_chief")
        mea_strategy_payload = self._compact_strategy_payload(strategy_payload, agent_role="macro_event_analyst")
        pm_market_payload = self._compact_market_payload(market, agent_role="pm")
        rt_market_payload = self._compact_market_payload(market, agent_role="risk_trader")
        mea_market_payload = self._compact_market_payload(market, agent_role="macro_event_analyst")
        chief_market_payload = self._compact_market_payload(market, agent_role="crypto_chief")
        compiled_execution_contexts = execution_contexts or self.compile_execution_contexts(
            market=market,
            policies=policies,
            forecasts=forecasts,
            strategy_payload=strategy_payload,
        )
        rt_execution_contexts = self._compact_execution_contexts(compiled_execution_contexts, agent_role="risk_trader")
        chief_execution_contexts = self._compact_execution_contexts(compiled_execution_contexts, agent_role="crypto_chief")
        macro_prices_payload: dict[str, Any] = {}
        if macro_snapshot is not None:
            if hasattr(macro_snapshot, "model_dump"):
                macro_prices_payload = macro_snapshot.model_dump(mode="json")
            elif isinstance(macro_snapshot, dict):
                macro_prices_payload = macro_snapshot
        latest_macro_brief_payload = self._latest_macro_brief_runtime_payload()
        daily_pnl_panel_payload = (
            self.memory_assets.daily_pnl_panel() if self.memory_assets is not None else {}
        )
        decision_context_payload = self._build_pm_decision_context(
            market=market,
            strategy_payload=strategy_payload or {},
            latest_macro_brief_payload=latest_macro_brief_payload,
        )
        # Chief retro 2026-04-24 directive support panels — surfaced into
        # role-specific runtime_packs so each agent sees the data the
        # directive needs them to reason about.
        consecutive_holds_payload = self._compute_consecutive_holds(
            strategy_payload=strategy_payload
        )
        regime_drift_payload = self._compute_regime_drift_indicators()
        theoretical_ceiling_payload = self._compute_theoretical_profit_ceiling(
            strategy_payload=strategy_payload
        )
        pm_payload = {
            "trace_id": trace_id,
            "decision_context": decision_context_payload,
            "daily_pnl_panel": daily_pnl_panel_payload,
            "theoretical_profit_ceiling": theoretical_ceiling_payload,
            "market": pm_market_payload,
            "risk_limits": {coin: self._policy_payload(policy) for coin, policy in policies.items()},
            "risk_brake_policy": self._risk_brake_policy_payload(),
            "forecasts": self._forecast_payload(forecasts),
            "news_events": self._compact_news_events(news_events, limit=8),
            "previous_strategy": strategy_payload or {},
            "macro_memory": list(macro_memory or []),
            "macro_prices": macro_prices_payload,
            "latest_macro_brief": latest_macro_brief_payload,
            "pending_learning_directives": self._pending_learning_directives_payload("pm"),
        }
        return {
            "pm": AgentRuntimeInput(
                input_id=new_id("input"),
                agent_role="pm",
                task_kind="strategy",
                payload=pm_payload,
            ),
            "risk_trader": AgentRuntimeInput(
                input_id=new_id("input"),
                agent_role="risk_trader",
                task_kind="execution",
                payload={
                    "trace_id": trace_id,
                    "market": rt_market_payload,
                    "daily_pnl_panel": daily_pnl_panel_payload,
                    "consecutive_holds": consecutive_holds_payload,
                    "theoretical_profit_ceiling": theoretical_ceiling_payload,
                    "risk_limits": {coin: self._policy_payload(policy) for coin, policy in policies.items()},
                    "forecasts": self._forecast_payload(forecasts),
                    "news_events": self._compact_news_events(news_events, limit=5),
                    "strategy": rt_strategy_payload,
                    "execution_contexts": rt_execution_contexts,
                    "macro_prices": macro_prices_payload,
                    "latest_macro_brief": latest_macro_brief_payload,
                    "pending_learning_directives": self._pending_learning_directives_payload("risk_trader"),
                },
            ),
            "macro_event_analyst": AgentRuntimeInput(
                input_id=new_id("input"),
                agent_role="macro_event_analyst",
                task_kind="event_summary",
                payload={
                    "trace_id": trace_id,
                    "market": mea_market_payload,
                    "daily_pnl_panel": daily_pnl_panel_payload,
                    "regime_drift_indicators": regime_drift_payload,
                    "news_events": [item.model_dump(mode="json") for item in news_events],
                    "macro_memory": list(macro_memory or []),
                    "latest_strategy": mea_strategy_payload,
                    "recent_news_submissions": self._recent_mea_submissions_digest(limit=3),
                    "macro_prices": macro_prices_payload,
                    "latest_macro_brief": latest_macro_brief_payload,
                    "pending_learning_directives": self._pending_learning_directives_payload("macro_event_analyst"),
                },
            ),
            "crypto_chief": AgentRuntimeInput(
                input_id=new_id("input"),
                agent_role="crypto_chief",
                task_kind="retro",
                payload={
                    **{**pm_payload, "market": chief_market_payload},
                    "previous_strategy": chief_strategy_payload,
                    "execution_contexts": chief_execution_contexts,
                    "consecutive_holds": consecutive_holds_payload,
                    "regime_drift_indicators": regime_drift_payload,
                    "pending_learning_directives": self._pending_learning_directives_payload("crypto_chief"),
                },
            ),
        }

    def compile_execution_contexts(
        self,
        *,
        market: DataIngestBundle,
        policies: dict[str, GuardDecision],
        forecasts: dict[str, CoinForecast],
        strategy_payload: dict | None,
    ) -> list[dict[str, Any]]:
        if not strategy_payload:
            return []
        total_equity = float(market.portfolio.total_equity_usd or 0.0)
        contexts: list[dict[str, Any]] = []
        for target in strategy_payload.get("targets", []):
            if not isinstance(target, dict):
                continue
            coin = str(target.get("symbol") or "").upper()
            account = market.accounts.get(coin)
            snapshot = market.market.get(coin)
            if not coin or account is None or snapshot is None or coin not in policies:
                continue
            current_share = notional_to_pct_of_exposure_budget(
                notional_usd=account.current_notional_usd,
                total_equity_usd=total_equity,
                max_leverage=policies[coin].risk_limits.max_leverage,
            )
            contexts.append(
                {
                    "context_id": new_id("execctx"),
                    "strategy_id": strategy_payload.get("strategy_id"),
                    "coin": coin,
                    "product_id": snapshot.product_id,
                    "target": target,
                    "current_position_share_pct_of_exposure_budget": round(current_share, 4),
                    "market_snapshot": snapshot.model_dump(mode="json"),
                    "account_snapshot": account.model_dump(mode="json"),
                    "risk_limits": policies[coin].risk_limits.model_dump(mode="json"),
                    "position_risk_state": policies[coin].position_risk_state.model_dump(mode="json"),
                    "portfolio_risk_state": policies[coin].portfolio_risk_state.model_dump(mode="json"),
                    "forecast_snapshot": self._forecast_payload(
                        {coin: forecasts[coin]} if coin in forecasts else {}
                    ).get(coin, {}),
                    "product_metadata": market.product_metadata.get(coin).model_dump(mode="json")
                    if coin in market.product_metadata
                    else {},
                    "execution_history": market.execution_history.get(coin).model_dump(mode="json")
                    if coin in market.execution_history
                    else {},
                }
            )
        return contexts

    def _risk_brake_policy_payload(self) -> dict[str, Any]:
        risk = self.policy_risk.settings.risk if self.policy_risk is not None else None
        return {
            "position_peak_drawdown_pct": {
                "observe": float(getattr(risk, "position_observe_drawdown_pct", 0.8)),
                "reduce": float(getattr(risk, "position_reduce_drawdown_pct", 1.4)),
                "exit": float(getattr(risk, "position_exit_drawdown_pct", 2.2)),
            },
            "portfolio_peak_drawdown_pct": {
                "observe": float(getattr(risk, "portfolio_peak_observe_drawdown_pct", 0.6)),
                "reduce": float(getattr(risk, "portfolio_peak_reduce_drawdown_pct", 1.0)),
                "exit": float(getattr(risk, "portfolio_peak_exit_drawdown_pct", 1.8)),
            },
            "system_actions": {
                "observe": "record_only",
                "reduce": "system_auto_reduce_then_wake_pm_rt",
                "exit": "system_auto_exit_then_wake_pm_rt",
            },
            "lock_release": "new_pm_strategy_revision",
        }

    # Default brief TTL: 36h (daily cadence + 12h slack — matches spec 014 NFR-005).
    _MACRO_BRIEF_VALID_HOURS_DEFAULT = 36.0
    _MACRO_BRIEF_CONSECUTIVE_FALSIFIED_THRESHOLD = 3

    # Spec 015 scenario 3: decision_context alignment thresholds.
    _DECISION_CONTEXT_DIVERGED_PCT = 1.0  # |price_move| > 1% and direction mismatch → diverged
    _DECISION_CONTEXT_ALIGNED_PCT = 0.5   # |price_move| < 0.5% or same direction → aligned

    def _build_pm_decision_context(
        self,
        *,
        market: DataIngestBundle,
        strategy_payload: dict[str, Any],
        latest_macro_brief_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Spec 015 FR-007: top-level `decision_context` block PM reads first.

        Returns an aggregated view of:
        - `regime_summary` from Chief brief
        - `price_snapshot` (BTC / ETH mark + 24h move from compressed series)
        - `last_thesis_evidence_breakdown` from the previous strategy
        - `thesis_price_alignment_flag` (aligned / diverged / unknown)
        """
        regime_summary = None
        brief = latest_macro_brief_payload.get("brief") if latest_macro_brief_payload else None
        if isinstance(brief, dict):
            regime_tags = dict(brief.get("regime_tags") or {})
            regime_summary = regime_tags.get("regime_summary")
        if latest_macro_brief_payload and latest_macro_brief_payload.get("missing"):
            regime_summary = "unknown_brief_missing"
        elif latest_macro_brief_payload and latest_macro_brief_payload.get("stale"):
            regime_summary = regime_summary or "unknown_brief_stale"

        price_snapshot = self._build_decision_context_price_snapshot(market)
        last_thesis_evidence_breakdown = self._extract_evidence_breakdown(strategy_payload)
        alignment_flag = self._compute_thesis_price_alignment_flag(
            strategy_payload=strategy_payload,
            price_snapshot=price_snapshot,
        )
        band_revision_streak = self._compute_band_revision_streak()
        return {
            "regime_summary": regime_summary,
            "price_snapshot": price_snapshot,
            "last_thesis_evidence_breakdown": last_thesis_evidence_breakdown,
            "thesis_price_alignment_flag": alignment_flag,
            "macro_brief_age_hours": (latest_macro_brief_payload or {}).get("age_hours"),
            "chief_regime_confidence": (latest_macro_brief_payload or {}).get(
                "chief_regime_confidence", "ok"
            ),
            "band_revision_streak": band_revision_streak,
        }

    def _compute_band_revision_streak(self, *, max_lookback: int = 8) -> dict[str, Any]:
        """Chief retro 2026-04-24 directive support.

        Counts consecutive most-recent PM submissions that share the same
        target_gross_exposure_band_pct AND primary direction. ≥3 same-band
        revisions are the warning signal: the next revision must either
        widen the working band or explicitly surrender the daily target.

        Returns: count, current_band, current_direction, since_rev, warning.
        """
        empty = {
            "count": 0,
            "current_band": None,
            "current_direction": None,
            "since_rev": None,
            "warning": None,
        }
        if self.memory_assets is None:
            return empty
        recent = self.memory_assets.recent_assets(
            asset_type="strategy", actor_role="pm", limit=max_lookback
        )
        if not recent:
            return empty
        fingerprints: list[tuple[Any, str, Any]] = []
        for asset in recent:
            payload = dict(asset.get("payload") or {})
            band_raw = payload.get("target_gross_exposure_band_pct")
            band_tup: tuple[float, float] | None = None
            if isinstance(band_raw, (list, tuple)) and len(band_raw) == 2:
                try:
                    band_tup = (float(band_raw[0]), float(band_raw[1]))
                except (TypeError, ValueError):
                    band_tup = None
            primary_dir = "flat"
            for tgt in payload.get("targets") or []:
                if not isinstance(tgt, dict):
                    continue
                state = str(tgt.get("state") or "").lower()
                direction = str(tgt.get("direction") or "").lower()
                if state == "active" and direction in ("long", "short"):
                    primary_dir = direction
                    break
            fingerprints.append((band_tup, primary_dir, payload.get("revision_number")))
        head_band, head_dir, _ = fingerprints[0]
        streak = 1
        since_rev = fingerprints[0][2]
        for band, dir_, rev in fingerprints[1:]:
            if band == head_band and dir_ == head_dir:
                streak += 1
                since_rev = rev  # earliest matching rev
            else:
                break
        warning: str | None = None
        if streak >= 3:
            warning = (
                "≥3 consecutive same-band same-direction revisions; per Chief retro "
                "2026-04-24 directive, next submit must widen the working band OR "
                "explicitly mark the daily target as surrendered."
            )
        elif streak == 2:
            warning = (
                "2 consecutive same-band revisions; if next submit also stays in this "
                "band+direction without widening, the directive triggers."
            )
        return {
            "count": streak,
            "current_band": list(head_band) if head_band is not None else None,
            "current_direction": head_dir,
            "since_rev": since_rev,
            "warning": warning,
        }

    _RT_ENTRY_OR_SCALE_ACTIONS = frozenset({"open", "add", "reduce", "flip"})

    def _compute_consecutive_holds(
        self,
        *,
        strategy_payload: dict[str, Any] | None,
        max_lookback: int = 6,
    ) -> dict[str, Any]:
        """Chief retro 2026-04-24 directive support for RT.

        Counts consecutive most-recent RT execution_batches with no entry/scale
        decision (per user definition, "hold" = no action in {open, add,
        reduce, flip}). When PM is in active long + risk_state=normal +
        current exposure < band midpoint, ≥2 consecutive holds means RT is
        substituting "wait for confirmation" for legitimate scale-up — the
        directive requires writing wait condition, miss cost, and a challenge
        to PM on the third batch.

        Returns: count, last_action, gap_to_band_mid_pct (positive = below
        mid, room to add), warning.
        """
        empty = {
            "count": 0,
            "last_action": None,
            "gap_to_band_mid_pct": None,
            "warning": None,
        }
        if self.memory_assets is None:
            return empty
        batches = self.memory_assets.recent_assets(
            asset_type="execution_batch", actor_role="risk_trader", limit=max_lookback
        )
        streak = 0
        last_action_label: str | None = None
        for asset in batches:
            payload = dict(asset.get("payload") or {})
            decisions = payload.get("decisions") or []
            saw_active = False
            for d in decisions:
                if not isinstance(d, dict):
                    continue
                action = str(d.get("action") or "").lower()
                if action in self._RT_ENTRY_OR_SCALE_ACTIONS:
                    saw_active = True
                    break
            if saw_active:
                last_action_label = last_action_label or "entry_or_scale"
                break
            streak += 1
            last_action_label = last_action_label or "hold"
        envelope = self._compute_exposure_envelope(strategy_payload)
        gap_to_mid = envelope.get("gap_to_band_mid_pct_of_budget") if envelope else None
        gap_to_ceiling = envelope.get("gap_to_envelope_ceiling_pct_of_budget") if envelope else None
        warning: str | None = None
        if streak >= 2 and gap_to_mid is not None and gap_to_mid > 0:
            warning = (
                "≥2 consecutive holds while exposure sits below band midpoint with room "
                "to scale; per Chief retro 2026-04-24 directive, next batch must write "
                "explicit wait condition + miss cost + challenge to PM, OR add."
            )
        return {
            "count": streak,
            "last_action": last_action_label,
            # Unit: % of exposure_budget (= equity × max_leverage), matching
            # the unit PM uses for target_exposure_band_pct + rt_discretion_band_pct.
            "gap_to_band_mid_pct": gap_to_mid,
            "gap_to_envelope_ceiling_pct": gap_to_ceiling,
            "current_pct_of_exposure_budget": envelope.get("current_pct_of_budget") if envelope else None,
            "envelope_ceiling_pct_of_budget": envelope.get("envelope_ceiling_pct_of_budget") if envelope else None,
            "warning": warning,
        }

    def _compute_exposure_envelope(
        self, strategy_payload: dict[str, Any] | None
    ) -> dict[str, float | None] | None:
        """Compute RT's actual exposure envelope vs PM's authorization, using
        the SAME unit PM uses for target_exposure_band_pct (% of
        exposure_budget = equity × max_leverage). Earlier version of this
        helper used (notional / equity) which is in a DIFFERENT unit and
        makes the "gap to band" answer wrong by ~leverage × — e.g. on a
        4-26 BTC position the equity-unit gap looked like -14.77 (meaning
        "way over") when in budget unit RT was actually at +1.05 below mid
        (still room to add). Per spec 015 strategy contract: 所有持仓/暴露
        相关百分比统一按 `total_equity_usd * max_leverage` 的 exposure
        budget 口径表达.

        Returns dict with:
          current_pct_of_budget: notional / (equity × leverage) × 100
          band_lo / band_hi / band_mid: from PM's target_gross_exposure_band_pct
          discretion_pct: max rt_discretion_band_pct across active targets
          envelope_ceiling_pct_of_budget: band_hi + discretion (the real
            ceiling RT can move to without violating PM)
          gap_to_band_mid_pct_of_budget: band_mid - current; positive = below
          gap_to_envelope_ceiling_pct_of_budget: envelope_ceiling - current
        """
        if not strategy_payload or self.memory_assets is None:
            return None
        band_raw = strategy_payload.get("target_gross_exposure_band_pct")
        if not isinstance(band_raw, (list, tuple)) or len(band_raw) != 2:
            return None
        try:
            band_lo, band_hi = float(band_raw[0]), float(band_raw[1])
        except (TypeError, ValueError):
            return None
        # Discretion: take the max across active targets — that's the largest
        # extra envelope RT may use anywhere.
        discretion = 0.0
        for t in strategy_payload.get("targets") or []:
            if not isinstance(t, dict):
                continue
            if str(t.get("state") or "").lower() != "active":
                continue
            try:
                d = float(t.get("rt_discretion_band_pct") or 0.0)
            except (TypeError, ValueError):
                continue
            if d > discretion:
                discretion = d
        portfolio = self.memory_assets.latest_asset(asset_type="portfolio_snapshot") or self.memory_assets.latest_portfolio()
        if not portfolio:
            return None
        try:
            payload = dict(portfolio.get("payload") or {})
            equity = float(payload.get("total_equity_usd") or 0)
            exposure_notional = float(payload.get("total_exposure_usd") or 0)
            if equity <= 0:
                return None
            # Pull leverage from the largest position; default 1 if missing.
            leverage = 1.0
            positions = payload.get("positions") or []
            if positions and isinstance(positions[0], dict):
                try:
                    leverage = float(positions[0].get("leverage") or 1.0) or 1.0
                except (TypeError, ValueError):
                    leverage = 1.0
            exposure_budget = equity * leverage
            if exposure_budget <= 0:
                return None
            current_pct_of_budget = exposure_notional / exposure_budget * 100.0
            band_mid = (band_lo + band_hi) / 2.0
            envelope_ceiling = band_hi + discretion
            return {
                "current_pct_of_budget": round(current_pct_of_budget, 2),
                "band_lo": round(band_lo, 2),
                "band_hi": round(band_hi, 2),
                "band_mid": round(band_mid, 2),
                "discretion_pct": round(discretion, 2),
                "envelope_ceiling_pct_of_budget": round(envelope_ceiling, 2),
                "gap_to_band_mid_pct_of_budget": round(band_mid - current_pct_of_budget, 2),
                "gap_to_envelope_ceiling_pct_of_budget": round(envelope_ceiling - current_pct_of_budget, 2),
                "leverage_assumed": round(leverage, 2),
            }
        except (TypeError, ValueError):
            return None

    def _compute_regime_drift_indicators(
        self, *, max_lookback_news: int = 20, max_lookback_bridge: int = 1500
    ) -> dict[str, Any]:
        """Chief retro 2026-04-24 directive support for MEA.

        Surfaces three signals MEA needs to translate "no new headline" into a
        strategy-relevant statement instead of a default empty submission:
        - zero_event_streak: how many consecutive recent news_submissions had
          no events (long streak + improving prices = "regime is relaxing,
          tell PM what's left to widen")
        - hours_since_last_event: time since last real macro_event
        - brent_delta_24h_pct: derived from runtime_bridge_state history
        - btc_change_pct_24h: derived from runtime_bridge_state history
        """
        result: dict[str, Any] = {
            "zero_event_streak": 0,
            "hours_since_last_event": None,
            "brent_delta_24h_pct": None,
            "btc_change_pct_24h": None,
        }
        if self.memory_assets is None:
            return result
        recent_news = self.memory_assets.recent_assets(
            asset_type="news_submission", limit=max_lookback_news
        )
        for asset in recent_news:
            events = (asset.get("payload") or {}).get("events") or []
            if events:
                break
            result["zero_event_streak"] += 1
        latest_event = self.memory_assets.recent_assets(asset_type="macro_event", limit=1)
        if latest_event:
            ts_raw = latest_event[0].get("created_at")
            try:
                ts_dt = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                if ts_dt.tzinfo is None:
                    ts_dt = ts_dt.replace(tzinfo=UTC)
                hours = (datetime.now(UTC) - ts_dt.astimezone(UTC)).total_seconds() / 3600.0
                result["hours_since_last_event"] = round(hours, 1)
            except Exception:  # noqa: BLE001
                pass
        # Use targeted SQL helper that pulls only the 4 scalar fields needed
        # via json_extract. Replaces a previous recent_assets(limit=1500)
        # scan that hauled MB of full bridge payload per refresh and
        # dominated bridge cycle wall time on 2026-04-25 instrumentation.
        target_iso = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        latest_pair, prior_pair = self.memory_assets.runtime_bridge_macro_market_pair_24h(target_iso)
        if latest_pair is not None and prior_pair is not None:
            result["brent_delta_24h_pct"] = self._pct_delta_scalar(
                latest_pair.get("brent_price"), prior_pair.get("brent_price")
            )
            result["btc_change_pct_24h"] = self._pct_delta_scalar(
                latest_pair.get("btc_mark_price"), prior_pair.get("btc_mark_price")
            )
        return result

    @staticmethod
    def _pct_delta_scalar(current: float | None, prior: float | None) -> float | None:
        if current is None or prior is None:
            return None
        try:
            current_v = float(current)
            prior_v = float(prior)
        except (TypeError, ValueError):
            return None
        if prior_v <= 0:
            return None
        return round((current_v - prior_v) / prior_v * 100.0, 3)

    def _compute_theoretical_profit_ceiling(
        self, *, strategy_payload: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Chief retro 2026-04-24 directive support: quantify the gap between
        what was achievable today and what the current authorization allows.

        Pulls today's BTC max-favorable mark move (in PM's stated direction)
        from the live mark_price embedded in `portfolio_snapshot.positions[0].
        raw.mark_price.value` (this path bypasses the cached product call so
        the history is real). Projects that move onto:
          - current actual notional (= what we'd realize if held all day)
          - PM's band upper × leverage (max if RT used full band, no
            discretion)
          - PM's band upper + discretion × leverage (the REAL envelope
            ceiling RT can use without violating PM)
        All output PnL ceilings are in % of equity (the unit owner cares
        about for P&L impact).

        Spec 015 / strategy contract: target_exposure_band_pct +
        rt_discretion_band_pct are in % of exposure_budget (= equity ×
        leverage). Earlier version of this helper conflated that with %
        of equity, undercounting the discretion-side ceiling by leverage.
        """
        result: dict[str, Any] = {
            "max_favorable_pct": None,
            "primary_direction": None,
            "current_notional_share_of_equity_pct": None,
            "band_upper_pct_of_budget": None,
            "discretion_pct_of_budget": None,
            "envelope_ceiling_pct_of_budget": None,
            "ceiling_at_current_pct_of_equity": None,
            "ceiling_at_band_upper_pct_of_equity": None,
            "ceiling_at_envelope_pct_of_equity": None,
        }
        if self.memory_assets is None or not strategy_payload:
            return result
        primary_dir = None
        max_discretion = 0.0
        for tgt in strategy_payload.get("targets") or []:
            if not isinstance(tgt, dict):
                continue
            state = str(tgt.get("state") or "").lower()
            direction = str(tgt.get("direction") or "").lower()
            if state == "active" and primary_dir is None and direction in ("long", "short"):
                primary_dir = direction
            try:
                d = float(tgt.get("rt_discretion_band_pct") or 0.0)
            except (TypeError, ValueError):
                d = 0.0
            if state == "active" and d > max_discretion:
                max_discretion = d
        result["primary_direction"] = primary_dir
        result["discretion_pct_of_budget"] = round(max_discretion, 2)
        band_raw = strategy_payload.get("target_gross_exposure_band_pct")
        band_upper: float | None = None
        if isinstance(band_raw, (list, tuple)) and len(band_raw) == 2:
            try:
                band_upper = float(band_raw[1])
                result["band_upper_pct_of_budget"] = round(band_upper, 2)
                result["envelope_ceiling_pct_of_budget"] = round(band_upper + max_discretion, 2)
            except (TypeError, ValueError):
                band_upper = None
        # Today's BTC range from live position marks
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        marks_raw = self.memory_assets.btc_position_marks_since(today_start.isoformat())
        if not marks_raw:
            return result
        marks: list[float] = [m for _, m in marks_raw if m > 0]
        if not marks:
            return result
        open_mark = marks[0]
        if open_mark <= 0:
            return result
        high = max(marks)
        low = min(marks)
        if primary_dir == "long":
            max_favorable = (high - open_mark) / open_mark * 100.0
        elif primary_dir == "short":
            max_favorable = (open_mark - low) / open_mark * 100.0
        else:
            max_favorable = max(high - open_mark, open_mark - low) / open_mark * 100.0
        result["max_favorable_pct"] = round(max_favorable, 3)
        # Project to PnL-as-%-of-equity ceilings.
        portfolio = self.memory_assets.latest_asset(asset_type="portfolio_snapshot") or self.memory_assets.latest_portfolio()
        if not portfolio:
            return result
        payload = dict(portfolio.get("payload") or {})
        try:
            equity = float(payload.get("total_equity_usd") or 0)
            current_notional = float(payload.get("total_exposure_usd") or 0)
            if equity <= 0:
                return result
        except (TypeError, ValueError):
            return result
        leverage = 1.0
        positions = payload.get("positions") or []
        if positions and isinstance(positions[0], dict):
            try:
                leverage = float(positions[0].get("leverage") or 1.0) or 1.0
            except (TypeError, ValueError):
                leverage = 1.0
        # Current realised exposure as % of equity (different unit from
        # band! — kept for owner-facing P&L intuition).
        result["current_notional_share_of_equity_pct"] = round(current_notional / equity * 100.0, 2)
        # PnL = notional × move%. As %-of-equity = notional / equity × move%.
        result["ceiling_at_current_pct_of_equity"] = round(
            current_notional / equity * max_favorable / 100.0 * 100.0, 4
        )
        # If RT had used full band: max_notional_at_band = band_upper% × equity × leverage
        # PnL/equity = band_upper × leverage × move% / 100 / 100
        if band_upper is not None:
            ceiling_band = band_upper * leverage * max_favorable / 10000.0 * 100.0
            result["ceiling_at_band_upper_pct_of_equity"] = round(ceiling_band, 4)
            envelope_pct = band_upper + max_discretion
            ceiling_env = envelope_pct * leverage * max_favorable / 10000.0 * 100.0
            result["ceiling_at_envelope_pct_of_equity"] = round(ceiling_env, 4)
        return result

    @staticmethod
    def _build_decision_context_price_snapshot(market: DataIngestBundle) -> dict[str, Any]:
        snapshot: dict[str, Any] = {}
        for coin in ("BTC", "ETH"):
            entry = market.market.get(coin) if market is not None else None
            if entry is None:
                continue
            try:
                mark_price = float(entry.mark_price) if entry.mark_price is not None else None
            except (TypeError, ValueError):
                mark_price = None
            change_pct_24h = None
            context_entry = market.market_context.get(coin) if market is not None else None
            if context_entry is not None:
                series_dict = dict(context_entry.compressed_price_series or {})
                # The "24h" key in compressed_price_series is misleading — in
                # live data it carries ~90 DAILY bars (~3 months of history),
                # not a 24-hour span. Prefer "15m" (96 bars × 15min = 24h) or
                # "1h" (12 bars × 1h = 12h) instead. Upstream `change_pct`
                # field is also observed inconsistent; compute from points.
                candidate_series = (
                    series_dict.get("15m")
                    or series_dict.get("1h")
                    or series_dict.get("4h")
                    or series_dict.get("24h")
                )
                if candidate_series is not None:
                    points = list(getattr(candidate_series, "points", []) or [])
                    if len(points) >= 2:
                        try:
                            first_close = float(getattr(points[0], "close", None))
                            last_close = float(getattr(points[-1], "close", None))
                            if first_close > 0:
                                change_pct_24h = round(
                                    (last_close - first_close) / first_close * 100.0, 4
                                )
                        except (TypeError, ValueError, AttributeError):
                            change_pct_24h = None
            snapshot[coin] = {
                "mark": mark_price,
                "change_pct_24h": change_pct_24h,
            }
        return snapshot

    @staticmethod
    def _extract_evidence_breakdown(strategy_payload: dict[str, Any]) -> dict[str, Any] | None:
        if not strategy_payload:
            return None
        change_summary = strategy_payload.get("change_summary")
        if isinstance(change_summary, dict):
            breakdown = change_summary.get("evidence_breakdown")
            if isinstance(breakdown, dict):
                return dict(breakdown)
        return None

    @classmethod
    def _compute_thesis_price_alignment_flag(
        cls,
        *,
        strategy_payload: dict[str, Any],
        price_snapshot: dict[str, Any],
    ) -> str:
        """Derive aligned/diverged/unknown per spec 015 scenario 3.

        Very coarse heuristic for MVP: look at the primary (priority=1) BTC
        target's direction and compare to BTC's 24h change sign. If direction
        contradicts price movement AND magnitude > threshold → diverged. If
        same-direction or magnitude < aligned-threshold → aligned. Else unknown.
        """
        if not strategy_payload:
            return "unknown"
        targets = [
            item for item in (strategy_payload.get("targets") or [])
            if isinstance(item, dict)
        ]
        if not targets:
            return "unknown"
        targets.sort(key=lambda item: int(item.get("priority") or 99))
        primary = next(
            (item for item in targets if str(item.get("symbol") or "").upper() == "BTC"),
            targets[0],
        )
        coin = str(primary.get("symbol") or "").upper()
        direction = str(primary.get("direction") or "").strip().lower()
        entry = price_snapshot.get(coin) or {}
        change_pct = entry.get("change_pct_24h")
        try:
            change_pct_value = float(change_pct) if change_pct is not None else None
        except (TypeError, ValueError):
            change_pct_value = None
        if direction not in {"long", "short"} or change_pct_value is None:
            return "unknown"
        magnitude = abs(change_pct_value)
        if magnitude < cls._DECISION_CONTEXT_ALIGNED_PCT:
            return "aligned"
        if direction == "long" and change_pct_value < 0 and magnitude > cls._DECISION_CONTEXT_DIVERGED_PCT:
            return "diverged"
        if direction == "short" and change_pct_value > 0 and magnitude > cls._DECISION_CONTEXT_DIVERGED_PCT:
            return "diverged"
        if direction == "long" and change_pct_value > 0:
            return "aligned"
        if direction == "short" and change_pct_value < 0:
            return "aligned"
        return "unknown"

    def _latest_macro_brief_runtime_payload(self) -> dict[str, Any]:
        """Inject `latest_macro_brief` into runtime_pack with freshness flags.

        Payload shape:
            { missing: bool, stale: bool, age_hours: float | None,
              chief_regime_confidence: "ok" | "low",
              brief: dict | None }
        """
        if self.memory_assets is None:
            return {
                "missing": True,
                "stale": False,
                "age_hours": None,
                "chief_regime_confidence": "ok",
                "brief": None,
            }
        brief = self.memory_assets.latest_macro_brief()
        if brief is None:
            return {
                "missing": True,
                "stale": False,
                "age_hours": None,
                "chief_regime_confidence": "ok",
                "brief": None,
            }
        now = datetime.now(UTC)
        generated_at = self._parse_utc_iso(brief.get("generated_at_utc"))
        valid_until = self._parse_utc_iso(brief.get("valid_until_utc"))
        age_hours: float | None = None
        if generated_at is not None:
            age_hours = (now - generated_at).total_seconds() / 3600.0
        stale = False
        if valid_until is not None:
            stale = now > valid_until
        elif age_hours is not None:
            stale = age_hours > self._MACRO_BRIEF_VALID_HOURS_DEFAULT
        confidence = self._chief_regime_confidence_from_recent(
            self.memory_assets.recent_macro_briefs(
                limit=self._MACRO_BRIEF_CONSECUTIVE_FALSIFIED_THRESHOLD
            )
        )
        return {
            "missing": False,
            "stale": stale,
            "age_hours": round(age_hours, 2) if age_hours is not None else None,
            "chief_regime_confidence": confidence,
            "brief": brief,
        }

    @staticmethod
    def _parse_utc_iso(value: Any) -> datetime | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    @classmethod
    def _chief_regime_confidence_from_recent(cls, recent_briefs: list[dict[str, Any]]) -> str:
        """Spec 014 FR-012: consecutive falsified briefs → confidence=low."""
        if len(recent_briefs) < cls._MACRO_BRIEF_CONSECUTIVE_FALSIFIED_THRESHOLD:
            return "ok"
        considered = recent_briefs[: cls._MACRO_BRIEF_CONSECUTIVE_FALSIFIED_THRESHOLD]
        for item in considered:
            verdict = str(((item or {}).get("prior_brief_review") or {}).get("verdict") or "").strip()
            if verdict != "falsified":
                return "ok"
        return "low"

    def _pending_learning_directives_payload(self, agent_role: str) -> list[dict[str, Any]]:
        if self.memory_assets is None:
            return []
        directives = self.memory_assets.get_learning_directives(agent_role=agent_role, limit=20)
        pending = [
            directive
            for directive in directives
            if str(directive.get("completion_state") or "pending") == "pending"
        ]
        pending.sort(key=lambda item: str(item.get("issued_at_utc") or item.get("created_at_utc") or ""))
        return [
            {
                "directive_id": directive.get("directive_id") or directive.get("asset_id"),
                "cycle_id": directive.get("cycle_id"),
                "case_id": directive.get("case_id"),
                "directive": directive.get("directive"),
                "rationale": directive.get("rationale"),
                "session_key": directive.get("session_key"),
                "learning_path": directive.get("learning_path"),
                "issued_at_utc": directive.get("issued_at_utc"),
                "completion_state": directive.get("completion_state"),
            }
            for directive in pending
        ]

    def _build_retro_brief_runtime_payload(self, agent_role: str) -> dict[str, Any]:
        cycle_state, retro_case = self._latest_runtime_retro_context()
        brief = None
        case_id = str(retro_case.get("case_id") or "").strip()
        cycle_id = str(retro_case.get("cycle_id") or cycle_state.get("cycle_id") or "").strip()
        if case_id:
            brief = self.memory_assets.latest_retro_brief(
                case_id=case_id,
                cycle_id=cycle_id or None,
                agent_role=agent_role,
            )
        cycle_phase = str(cycle_state.get("state") or "").strip()
        is_closed = cycle_phase in {"completed", "failed"}
        pending_retro_case = retro_case if retro_case and brief is None and not is_closed else {}
        brief_status = {
            "cycle_id": cycle_id or None,
            "case_id": case_id or None,
            "agent_role": agent_role,
            "submitted": brief is not None,
            "brief_id": str((brief or {}).get("brief_id") or "") or None,
            "state": "submitted" if brief is not None else "pending" if pending_retro_case else "no_active_cycle",
            "cycle_state": cycle_phase or None,
        }
        return {
            "pending_retro_case": pending_retro_case,
            "retro_cycle_state": cycle_state,
            "retro_brief_status": brief_status,
        }

    def _latest_runtime_retro_context(self) -> tuple[dict[str, Any], dict[str, Any]]:
        if self.memory_assets is None:
            return {}, {}
        trade_day_utc = datetime.now(UTC).date().isoformat()
        cycle_state = dict(self.memory_assets.latest_retro_cycle_state(trade_day_utc=trade_day_utc) or {})
        if not cycle_state:
            cycle_state = dict(self.memory_assets.latest_retro_cycle_state() or {})
        retro_case: dict[str, Any] = {}
        case_id = str(cycle_state.get("retro_case_id") or "").strip()
        if case_id:
            retro_case = dict(self.memory_assets.get_retro_case(case_id=case_id) or {})
        if not retro_case:
            retro_case = dict(self.memory_assets.latest_retro_case(case_day_utc=trade_day_utc) or {})
        if not retro_case:
            retro_case = dict(self.memory_assets.latest_retro_case() or {})
        return cycle_state, retro_case

    def _recent_mea_submissions_digest(self, *, limit: int = 3) -> list[dict[str, Any]]:
        """Compact digest of MEA's own recent news submissions, for cross-turn dedup.

        MEA reads this to answer: "did I already report this event_id / theme recently?"
        and to avoid re-sending sessions_send about a theme already covered in the last pull.
        """
        if self.memory_assets is None:
            return []
        submissions = self.memory_assets.get_recent_news_submissions(limit=limit)
        digest: list[dict[str, Any]] = []
        for item in submissions:
            events = list(item.get("events") or [])
            digest.append(
                {
                    "submission_id": item.get("submission_id"),
                    "generated_at_utc": item.get("generated_at_utc"),
                    "event_count": len(events),
                    "events": [
                        {
                            "event_id": str(ev.get("event_id") or ""),
                            "category": str(ev.get("category") or ""),
                            "impact_level": str(ev.get("impact_level") or ""),
                            "summary": str(ev.get("summary") or "")[:160],
                        }
                        for ev in events
                    ],
                }
            )
        return digest

    def run_pm_submission(self, *, trace_id: str, runtime_input: AgentRuntimeInput) -> ValidatedSubmissionEnvelope:
        return self._run_submission_with_retry(
            trace_id=trace_id,
            runtime_input=runtime_input,
            submission_kind="strategy",
            agent_role="pm",
            task_kind="strategy",
            runner=self.pm_runner,
        )

    def run_rt_submission(self, *, trace_id: str, runtime_input: AgentRuntimeInput) -> ValidatedSubmissionEnvelope:
        return self._run_submission_with_retry(
            trace_id=trace_id,
            runtime_input=runtime_input,
            submission_kind="execution",
            agent_role="risk_trader",
            task_kind="execution",
            runner=self.risk_runner,
        )

    def run_mea_submission(
        self,
        *,
        trace_id: str,
        runtime_input: AgentRuntimeInput,
    ) -> ValidatedSubmissionEnvelope:
        return self._run_submission_with_retry(
            trace_id=trace_id,
            runtime_input=runtime_input,
            submission_kind="news",
            agent_role="macro_event_analyst",
            task_kind="event_summary",
            runner=self.macro_runner,
        )

    def prepare_retro_cycle(
        self,
        *,
        trace_id: str,
        runtime_inputs: dict[str, AgentRuntimeInput],
        trigger_type: str,
        case_day_utc: str | None = None,
        cycle_id: str | None = None,
        force_new_case: bool = False,
    ) -> dict[str, Any]:
        prepared = self.ensure_retro_case(
            trace_id=trace_id,
            runtime_inputs=runtime_inputs,
            trigger_type=trigger_type,
            case_day_utc=case_day_utc,
            cycle_id=cycle_id,
            force_new_case=force_new_case,
        )
        retro_case = dict(prepared.get("retro_case") or {})
        case_id = str(retro_case.get("case_id") or "")
        retro_briefs: list[dict[str, Any]] = []
        for agent_role in self._RETRO_BRIEF_ROLES:
            existing = self.memory_assets.latest_retro_brief(
                case_id=case_id,
                cycle_id=str(retro_case.get("cycle_id") or "") or None,
                agent_role=agent_role,
            )
            if existing is None:
                existing = self.run_retro_brief_submission(
                    trace_id=trace_id,
                    agent_role=agent_role,
                    runtime_input=runtime_inputs[agent_role],
                    retro_case=retro_case,
                )
            retro_briefs.append(existing)
        return {
            **prepared,
            "retro_briefs": retro_briefs,
        }

    def ensure_retro_case(
        self,
        *,
        trace_id: str,
        runtime_inputs: dict[str, AgentRuntimeInput],
        trigger_type: str,
        case_day_utc: str | None = None,
        cycle_id: str | None = None,
        force_new_case: bool = False,
    ) -> dict[str, Any]:
        resolved_case_day_utc = str(case_day_utc or datetime.now(UTC).date().isoformat())
        retro_case = None if force_new_case else self.memory_assets.latest_retro_case(case_day_utc=resolved_case_day_utc)
        if retro_case is None:
            retro_case = self.memory_assets.materialize_retro_case(
                trace_id=trace_id,
                authored_payload=self._build_retro_case_payload(
                    trigger_type=trigger_type,
                    runtime_inputs=runtime_inputs,
                    case_day_utc=resolved_case_day_utc,
                    cycle_id=cycle_id,
                ),
                actor_role="system",
                group_key=resolved_case_day_utc,
                metadata={"trigger_type": trigger_type},
            )
        return {
            "retro_case": retro_case,
            "runtime_inputs": runtime_inputs,
            "cycle_id": str((retro_case or {}).get("cycle_id") or cycle_id or ""),
        }

    def prepare_retro_cycle_from_runtime_bridge(
        self,
        *,
        trace_id: str,
        trigger_type: str,
        case_day_utc: str | None = None,
        cycle_id: str | None = None,
        force_new_case: bool = False,
    ) -> dict[str, Any]:
        runtime_bundle = self._resolve_runtime_bridge_bundle(
            agent_role="crypto_chief",
            trace_id=trace_id,
            trigger_type=trigger_type,
        )
        return self.prepare_retro_cycle(
            trace_id=trace_id,
            runtime_inputs=runtime_bundle["runtime_inputs"],
            trigger_type=trigger_type,
            case_day_utc=case_day_utc,
            cycle_id=cycle_id,
            force_new_case=force_new_case,
        )

    def ensure_retro_case_from_runtime_bridge(
        self,
        *,
        trace_id: str,
        trigger_type: str,
        case_day_utc: str | None = None,
        cycle_id: str | None = None,
        force_new_case: bool = False,
    ) -> dict[str, Any]:
        runtime_bundle = self._resolve_runtime_bridge_bundle(
            agent_role="crypto_chief",
            trace_id=trace_id,
            trigger_type=trigger_type,
        )
        return self.ensure_retro_case(
            trace_id=trace_id,
            runtime_inputs=runtime_bundle["runtime_inputs"],
            trigger_type=trigger_type,
            case_day_utc=case_day_utc,
            cycle_id=cycle_id,
            force_new_case=force_new_case,
        )

    def run_retro_brief_submission(
        self,
        *,
        trace_id: str,
        agent_role: str,
        runtime_input: AgentRuntimeInput,
        retro_case: dict[str, Any],
    ) -> dict[str, Any]:
        brief_submission = self.run_retro_brief_task(
            trace_id=trace_id,
            agent_role=agent_role,
            runtime_input=runtime_input,
            retro_case=retro_case,
        )
        return self._materialize_retro_brief_asset(
            trace_id=trace_id,
            agent_role=agent_role,
            retro_case=retro_case,
            brief_submission=brief_submission,
            source_ref=runtime_input.input_id,
        )

    def run_retro_brief_task(
        self,
        *,
        trace_id: str,
        agent_role: str,
        runtime_input: AgentRuntimeInput,
        retro_case: dict[str, Any],
    ) -> RetroBriefSubmission:
        task = AgentTask(
            task_id=new_id("task"),
            agent_role=agent_role,
            task_kind="retro_brief",
            input_id=runtime_input.input_id,
            trace_id=trace_id,
            session_id=self.session_id_for_role(agent_role),
            payload={
                "mode": "retro_brief",
                "instruction": (
                    "你在写自己的复盘 brief，不是在开同步会议。"
                    " 只返回一个纯 JSON 对象，包含 root_cause、cross_role_challenge、self_critique、tomorrow_change。"
                    " 每个字段都必须是非空字符串。不要 markdown，不要解释。"
                ),
                "retro_case": retro_case,
                "runtime_input": self._build_retro_runtime_summary(
                    speaker_role=agent_role,
                    runtime_input=runtime_input,
                ),
            },
        )
        reply = self._run_agent_task_with_retry(task=task)
        if reply.status == "needs_escalation":
            raise self._chief_retro_error(
                error_kind=f"{agent_role}_retro_brief_failed",
                raw_reply=str(reply.meta.get("stdout") or reply.meta.get("raw") or ""),
                stderr_summary=str(reply.meta.get("stderr") or ""),
                errors=[f"retro_brief_failed:{agent_role}"],
            )
        return self._validate_retro_brief_submission(
            agent_role=agent_role,
            payload=reply.payload or {},
            raw_reply=str(reply.meta.get("stdout") or reply.meta.get("raw") or ""),
            stderr_summary=str(reply.meta.get("stderr") or ""),
        )

    def _materialize_retro_brief_asset(
        self,
        *,
        trace_id: str,
        agent_role: str,
        retro_case: dict[str, Any],
        brief_submission: RetroBriefSubmission,
        source_ref: str,
    ) -> dict[str, Any]:
        brief_payload = self.memory_assets.materialize_retro_brief(
            trace_id=trace_id,
            case_id=str(retro_case.get("case_id") or ""),
            agent_role=agent_role,
            authored_payload=brief_submission.model_dump(mode="json"),
            cycle_id=str(retro_case.get("cycle_id") or ""),
            source_ref=source_ref,
            metadata={"trigger_type": str(retro_case.get("trigger_type") or "")},
        )
        self.memory_assets.save_agent_session(
            agent_role=agent_role,
            session_id=self.session_id_for_role(agent_role),
            last_task_kind="retro_brief",
            last_submission_kind="retro_brief",
        )
        self._record_events(
            [
                EventFactory.build(
                    trace_id=trace_id,
                    event_type="retro.brief.submitted",
                    source_module="agent_gateway",
                    entity_type="retro_brief",
                    entity_id=str(brief_payload.get("brief_id") or ""),
                    payload=brief_payload,
                )
            ]
        )
        return brief_payload

    def _validate_retro_brief_submission(
        self,
        *,
        agent_role: str,
        payload: dict[str, Any],
        raw_reply: str | None = None,
        stderr_summary: str | None = None,
    ) -> RetroBriefSubmission:
        try:
            brief_submission = RetroBriefSubmission.model_validate(payload or {})
        except ValidationError as exc:
            schema_ref, prompt_ref = self._retro_brief_contract_refs(agent_role)
            if raw_reply is None and stderr_summary is None:
                raise SubmissionValidationError(
                    schema_ref=schema_ref,
                    prompt_ref=prompt_ref,
                    errors=["invalid_retro_brief_payload"],
                    error_kind="retro_brief_invalid_payload",
                ) from exc
            raise self._chief_retro_error(
                error_kind=f"{agent_role}_retro_brief_invalid",
                raw_reply=str(raw_reply or ""),
                stderr_summary=str(stderr_summary or ""),
                errors=[f"retro_brief_invalid:{agent_role}", *[str(item.get("type") or "invalid") for item in exc.errors()]],
            ) from exc
        for field_name in ("root_cause", "cross_role_challenge", "self_critique", "tomorrow_change"):
            if str(getattr(brief_submission, field_name) or "").strip():
                continue
            schema_ref, prompt_ref = self._retro_brief_contract_refs(agent_role)
            if raw_reply is None and stderr_summary is None:
                raise SubmissionValidationError(
                    schema_ref=schema_ref,
                    prompt_ref=prompt_ref,
                    errors=[f"retro_brief_field_required:{field_name}"],
                    error_kind="retro_brief_invalid_payload",
                )
            raise self._chief_retro_error(
                error_kind=f"{agent_role}_retro_brief_invalid",
                raw_reply=str(raw_reply or ""),
                stderr_summary=str(stderr_summary or ""),
                errors=[f"retro_brief_field_required:{agent_role}:{field_name}"],
            )
        return brief_submission

    def _retro_brief_contract_refs(self, agent_role: str) -> tuple[str, str]:
        return (
            self._RETRO_BRIEF_SPEC_REF_BY_ROLE.get(agent_role, "specs/013-retro-rebuild/spec.md"),
            self._RETRO_BRIEF_PROMPT_REF_BY_ROLE.get(agent_role, "specs/013-retro-rebuild/quickstart.md"),
        )

    def _validate_retro_brief_lease(self, *, input_id: str) -> AgentRuntimeLease:
        self._require_runtime_bridge_dependencies()
        asset = self.memory_assets.get_asset(input_id)
        if asset is None or asset.get("asset_type") != "agent_runtime_lease":
            raise RuntimeInputLeaseError(reason="unknown_input_id", input_id=input_id, agent_role="retro_brief")
        lease = AgentRuntimeLease.model_validate(asset.get("payload") or {})
        if lease.pack.agent_role not in self._RETRO_BRIEF_ROLES:
            raise RuntimeInputLeaseError(
                reason="wrong_agent_role",
                input_id=input_id,
                agent_role="retro_brief",
                detail=str(lease.pack.agent_role),
            )
        return self._validate_runtime_lease(input_id=input_id, agent_role=lease.pack.agent_role)

    def run_chief_retro_synthesis(
        self,
        *,
        trace_id: str,
        runtime_input: AgentRuntimeInput,
        retro_case: dict[str, Any],
        retro_briefs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        learning_targets = self._capture_retro_learning_targets()
        session_id = self.session_id_for_role("crypto_chief")
        reply = self._run_agent_task_with_retry(
            task=AgentTask(
                task_id=new_id("task"),
                agent_role="crypto_chief",
                task_kind="retro",
                input_id=runtime_input.input_id,
                trace_id=trace_id,
                session_id=session_id,
                payload={
                    "mode": "retro_synthesis",
                    "instruction": (
                        "你不是在主持同步会议。你在阅读 retro_case 和三份 brief，然后给出裁决。"
                        " 只返回一个纯 JSON 对象。owner_summary 必须非空。"
                        " 可选包含 root_cause_ranking、role_judgements、learning_directives。"
                        " learning_directives 如果给出，必须覆盖需要学习的角色，且每项至少包含 agent_role、directive、rationale。"
                        " 不要 markdown，不要解释，不要 transcript。"
                    ),
                    "retro_case": retro_case,
                    "retro_briefs": retro_briefs,
                    "learning_targets": learning_targets,
                    "runtime_input": self._build_retro_runtime_summary(
                        speaker_role="crypto_chief",
                        runtime_input=runtime_input,
                    ),
                },
            )
        )
        if reply.status == "needs_escalation":
            raise self._chief_retro_error(
                error_kind=str(reply.meta.get("error_kind") or "agent_process_failed"),
                raw_reply=str(reply.meta.get("stdout") or reply.meta.get("raw") or ""),
                stderr_summary=str(reply.meta.get("stderr") or ""),
            )
        payload = self._normalize_chief_retro_payload(reply.payload)
        if not payload.get("owner_summary"):
            repair_reply = self._run_agent_task_with_retry(
                task=AgentTask(
                    task_id=new_id("task"),
                    agent_role="crypto_chief",
                    task_kind="retro",
                    input_id=runtime_input.input_id,
                    trace_id=trace_id,
                    session_id=session_id,
                    reply_contract="repair_json_only",
                    payload={
                        "mode": "retro_synthesis_repair",
                        "instruction": (
                            "返回一个纯 JSON 对象。owner_summary 必须非空。"
                            " 保留已有 case_id。可选保留 root_cause_ranking、role_judgements、learning_directives。"
                            " 不要 markdown，不要额外解释。"
                        ),
                        "previous_reply": reply.meta.get("stdout") or reply.meta.get("raw") or reply.payload,
                        "retro_case": retro_case,
                        "retro_briefs": retro_briefs,
                        "learning_targets": learning_targets,
                    },
                )
            )
            if repair_reply.status == "needs_escalation":
                raise self._chief_retro_error(
                    error_kind=str(repair_reply.meta.get("error_kind") or "agent_process_failed"),
                    raw_reply=str(repair_reply.meta.get("stdout") or repair_reply.meta.get("raw") or ""),
                    stderr_summary=str(repair_reply.meta.get("stderr") or ""),
                )
            payload = self._normalize_chief_retro_payload(repair_reply.payload)
            if not payload.get("owner_summary"):
                raise self._chief_retro_error(
                    error_kind="chief_owner_summary_required",
                    raw_reply=str(repair_reply.meta.get("stdout") or repair_reply.meta.get("raw") or ""),
                    stderr_summary=str(repair_reply.meta.get("stderr") or ""),
                    errors=["owner_summary_required"],
                )
        payload["case_id"] = str(payload.get("case_id") or retro_case.get("case_id") or "")
        return self._materialize_retro_outcome(
            trace_id=trace_id,
            input_id=runtime_input.input_id,
            payload=payload,
            source_ref=runtime_input.input_id,
            learning_targets=learning_targets,
        )

    def _prepared_retro_briefs(self, *, case_id: str, cycle_id: str | None = None) -> list[dict[str, Any]]:
        if not case_id:
            return []
        briefs: list[dict[str, Any]] = []
        for role in self._RETRO_BRIEF_ROLES:
            latest = self.memory_assets.latest_retro_brief(case_id=case_id, cycle_id=cycle_id, agent_role=role)
            if latest is not None:
                briefs.append(dict(latest))
        return briefs

    def _build_retro_case_payload(
        self,
        *,
        trigger_type: str,
        runtime_inputs: dict[str, AgentRuntimeInput],
        case_day_utc: str | None = None,
        cycle_id: str | None = None,
    ) -> dict[str, Any]:
        chief_payload = dict(runtime_inputs["crypto_chief"].payload or {})
        strategy_payload = dict(chief_payload.get("previous_strategy") or {})
        recent_strategy_assets = self.memory_assets.recent_assets(asset_type="strategy", limit=5)
        recent_execution_assets = self.memory_assets.recent_assets(asset_type="execution_batch", limit=8)
        recent_macro_assets = self.memory_assets.recent_assets(asset_type="macro_event", limit=8)
        recent_notification_assets = self.memory_assets.recent_assets(asset_type="notification_result", limit=8)
        strategy_id = str(strategy_payload.get("strategy_id") or "").strip()
        revision_number = strategy_payload.get("revision_number")
        objective_summary = "复盘为什么今天没有赚到 1%，把信号、风险、执行、消息治理拆开看。"
        if strategy_id:
            objective_summary += f" 当前主策略是 {strategy_id}"
            if revision_number is not None:
                objective_summary += f" rev {revision_number}"
            objective_summary += "。"
        return {
            "cycle_id": str(cycle_id or "").strip() or None,
            "case_day_utc": str(case_day_utc or datetime.now(UTC).date().isoformat()),
            "trigger_type": trigger_type,
            "primary_question": "为什么今天没有赚到 1%？",
            "objective_summary": objective_summary,
            "target_return_pct": 1.0,
            "challenge_prompts": [
                "PM 是否因为防守过度、翻向条件不清、或 band 调整过频而压缩了可赚空间？",
                "RT 是否因为执行节奏、等待确认、或缺少主动翻向而错过了可抓的战术收益？",
                "MEA 是否因为提醒过密、主题重复、或真正变化与噪音没有分清而干扰了决策？",
            ],
            "strategy_ids": [
                str(item.get("asset_id") or "")
                for item in recent_strategy_assets
                if item.get("asset_id")
            ],
            "execution_batch_ids": [
                str(item.get("asset_id") or "")
                for item in recent_execution_assets
                if item.get("asset_id")
            ],
            "macro_event_ids": [
                str(item.get("asset_id") or "")
                for item in recent_macro_assets
                if item.get("asset_id")
            ],
            "recent_notification_ids": [
                str(item.get("asset_id") or "")
                for item in recent_notification_assets
                if item.get("asset_id")
            ],
        }

    def _materialize_retro_outcome(
        self,
        *,
        trace_id: str,
        input_id: str,
        payload: dict[str, Any],
        source_ref: str,
        learning_targets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        submission = RetroSubmission.model_validate(payload or {})
        owner_summary = str(submission.owner_summary or "").strip()
        if not owner_summary:
            raise self._chief_retro_error(
                error_kind="chief_owner_summary_required",
                raw_reply="",
                stderr_summary="",
                errors=["owner_summary_required"],
            )
        reset_command = str(submission.reset_command or "/new").strip() or "/new"
        case_id = str(submission.case_id or "").strip() or None
        cycle_id = self._resolve_retro_cycle_id(case_id=case_id)
        learning_directives = self._normalize_learning_directive_submissions(submission.learning_directives)
        retro_payload = {
            "case_id": case_id,
            "cycle_id": cycle_id,
            "owner_summary": owner_summary,
            "reset_command": reset_command,
            "root_cause_ranking": list(submission.root_cause_ranking or []),
            "role_judgements": dict(submission.role_judgements or {}),
            "learning_directive_ids": [],
            "learning_directives": learning_directives,
        }
        retro_asset = self.memory_assets.save_asset(
            asset_type="chief_retro",
            payload=retro_payload,
            trace_id=trace_id,
            actor_role="crypto_chief",
            group_key=str(case_id or cycle_id or new_id("retro")),
            source_ref=source_ref,
            metadata={"input_id": input_id},
        )
        if owner_summary and self.notification_service is not None:
            self._record_events(
                self.notification_service.notify_owner_summary(
                    trace_id=trace_id,
                    owner_summary=owner_summary,
                )
            )
        self._record_events(
            [
                EventFactory.build(
                    trace_id=trace_id,
                    event_type="chief.retro.completed",
                    source_module="agent_gateway",
                    entity_type="chief_retro",
                    entity_id=str(retro_asset["asset_id"]),
                    payload={
                        "retro": retro_payload,
                        "retro_id": retro_asset["asset_id"],
                        "input_id": input_id,
                        "learning_directives": learning_directives,
                    },
                )
            ]
        )
        self.memory_assets.save_agent_session(
            agent_role="crypto_chief",
            session_id=self.session_id_for_role("crypto_chief"),
            last_task_kind="retro",
            last_submission_kind="retro",
        )
        return {
            "trace_id": trace_id,
            "input_id": input_id,
            "retro_id": retro_asset["asset_id"],
            "case_id": retro_payload["case_id"],
            "cycle_id": cycle_id,
            "owner_summary": owner_summary,
            "reset_command": reset_command,
            "root_cause_ranking": retro_payload["root_cause_ranking"],
            "role_judgements": retro_payload["role_judgements"],
            "learning_directives": learning_directives,
        }

    def _build_retro_runtime_summary(
        self,
        *,
        speaker_role: str,
        runtime_input: AgentRuntimeInput,
    ) -> dict[str, Any]:
        payload = dict(runtime_input.payload or {})
        source = dict(payload.get("retro_pack") or payload)
        summary: dict[str, Any] = {
            "trace_id": str(payload.get("trace_id") or source.get("trace_id") or ""),
            "speaker_role": speaker_role,
        }
        trigger_context = payload.get("trigger_context") or source.get("trigger_context")
        if trigger_context:
            summary["trigger_context"] = trigger_context
        market_summary = self._retro_market_summary(source.get("market") or {})
        if market_summary:
            summary["market_summary"] = market_summary
        risk_summary = self._retro_risk_summary(source.get("risk_limits") or {})
        if risk_summary:
            summary["risk_summary"] = risk_summary
        forecast_summary = self._retro_forecast_summary(source.get("forecasts") or {})
        if forecast_summary:
            summary["forecast_summary"] = forecast_summary
        strategy_payload = source.get("strategy") or source.get("previous_strategy") or {}
        strategy_summary = self._retro_strategy_summary(strategy_payload)
        if strategy_summary:
            summary["strategy_summary"] = strategy_summary
        news_summary = self._retro_news_summary(source.get("news_events") or [], limit=8)
        if news_summary:
            summary["news_summary"] = news_summary
        execution_summary = self._retro_execution_context_summary(source.get("execution_contexts") or [])
        if execution_summary:
            summary["execution_context_summary"] = execution_summary
        macro_memory_summary = self._retro_macro_memory_summary(source.get("macro_memory") or [])
        if macro_memory_summary:
            summary["macro_memory_summary"] = macro_memory_summary
        recent_execution_results = source.get("recent_execution_results") or []
        if recent_execution_results:
            summary["recent_execution_results"] = [
                {
                    "run_id": str(item.get("run_id") or ""),
                    "status": str(item.get("status") or ""),
                    "symbol": str(item.get("symbol") or ""),
                    "action": str(item.get("action") or ""),
                    "result_count": len(list(item.get("results") or [])),
                }
                for item in list(recent_execution_results)[:5]
                if isinstance(item, dict)
            ]
        recent_news_submissions = source.get("recent_news_submissions") or []
        if recent_news_submissions:
            summary["recent_news_submissions"] = [
                {
                    "submission_id": str(item.get("submission_id") or ""),
                    "event_count": len(list(item.get("events") or [])),
                }
                for item in list(recent_news_submissions)[:5]
                if isinstance(item, dict)
            ]
        return summary

    def _retro_market_summary(self, market_payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(market_payload or {})
        market = dict(payload.get("market") or {})
        accounts = dict(payload.get("accounts") or {})
        market_context = dict(payload.get("market_context") or {})
        execution_history = dict(payload.get("execution_history") or {})
        summary: dict[str, Any] = {}
        for coin in ("BTC", "ETH"):
            snapshot = dict(market.get(coin) or {})
            account = dict(accounts.get(coin) or {})
            context = dict(market_context.get(coin) or {})
            execution = dict(execution_history.get(coin) or {})
            if not snapshot and not account and not context and not execution:
                continue
            summary[coin] = {
                "mark_price": str(snapshot.get("mark_price") or ""),
                "funding_rate": str(snapshot.get("funding_rate") or ""),
                "open_interest": str(snapshot.get("open_interest") or ""),
                "day_notional_volume": str(snapshot.get("day_notional_volume") or ""),
                "trading_status": str(snapshot.get("trading_status") or ""),
                "shape_summary": str(context.get("shape_summary") or ""),
                "breakout_retest_state": str(dict(context.get("breakout_retest_state") or {}).get("state") or ""),
                "volatility_state": str(dict(context.get("volatility_state") or {}).get("state") or ""),
                "current_side": account.get("current_side"),
                "current_notional_usd": account.get("current_notional_usd"),
                "execution_summary": dict(execution.get("summary") or {}),
            }
        portfolio = dict(payload.get("portfolio") or {})
        if portfolio:
            summary["portfolio"] = {
                "total_equity_usd": str(portfolio.get("total_equity_usd") or ""),
                "available_equity_usd": str(portfolio.get("available_equity_usd") or ""),
                "total_exposure_usd": str(portfolio.get("total_exposure_usd") or ""),
                "position_count": len(list(portfolio.get("positions") or [])),
            }
        return summary

    @staticmethod
    def _retro_risk_summary(risk_limits: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for coin, payload in dict(risk_limits or {}).items():
            item = dict(payload or {})
            summary[str(coin)] = {
                "tradable": bool(dict(item.get("trade_availability") or {}).get("tradable", False)),
                "reasons": list(dict(item.get("trade_availability") or {}).get("reasons") or []),
                "max_leverage": dict(item.get("risk_limits") or {}).get("max_leverage"),
                "max_total_exposure_pct_of_exposure_budget": dict(item.get("risk_limits") or {}).get(
                    "max_total_exposure_pct_of_exposure_budget"
                ),
                "max_symbol_position_pct_of_exposure_budget": dict(item.get("risk_limits") or {}).get(
                    "max_symbol_position_pct_of_exposure_budget"
                ),
                "max_order_pct_of_exposure_budget": dict(item.get("risk_limits") or {}).get(
                    "max_order_pct_of_exposure_budget"
                ),
                "position_risk_state": str(dict(item.get("position_risk_state") or {}).get("state") or ""),
                "cooldown_active": bool(dict(item.get("cooldown") or {}).get("active", False)),
                "breaker_active": bool(dict(item.get("breaker") or {}).get("active", False)),
            }
        return summary

    @staticmethod
    def _retro_forecast_summary(forecasts: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for coin, payload in dict(forecasts or {}).items():
            horizon_summary: dict[str, Any] = {}
            for horizon in ("1h", "4h", "12h"):
                item = dict(dict(payload or {}).get(horizon) or {})
                if not item:
                    continue
                horizon_summary[horizon] = {
                    "side": str(item.get("side") or ""),
                    "confidence": item.get("confidence"),
                }
            if horizon_summary:
                summary[str(coin)] = horizon_summary
        return summary

    def _retro_strategy_summary(self, strategy_payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(strategy_payload or {})
        if not payload:
            return {}
        return {
            "strategy_id": str(payload.get("strategy_id") or ""),
            "revision_number": payload.get("revision_number"),
            "portfolio_mode": str(payload.get("portfolio_mode") or ""),
            "target_gross_exposure_band_pct": list(payload.get("target_gross_exposure_band_pct") or []),
            "portfolio_thesis": self._truncate_retro_text(str(payload.get("portfolio_thesis") or ""), 360),
            "portfolio_invalidation": self._truncate_retro_text(str(payload.get("portfolio_invalidation") or ""), 240),
            "flip_triggers": self._truncate_retro_text(str(payload.get("flip_triggers") or ""), 240),
            "change_summary": self._truncate_retro_text(str(payload.get("change_summary") or ""), 240),
            "targets": [
                {
                    "symbol": str(item.get("symbol") or ""),
                    "state": str(item.get("state") or ""),
                    "direction": str(item.get("direction") or ""),
                    "target_exposure_band_pct": list(item.get("target_exposure_band_pct") or []),
                    "rt_discretion_band_pct": item.get("rt_discretion_band_pct"),
                    "priority": item.get("priority"),
                }
                for item in list(payload.get("targets") or [])
                if isinstance(item, dict)
            ],
            "scheduled_rechecks": [
                {
                    "recheck_at_utc": str(item.get("recheck_at_utc") or ""),
                    "scope": str(item.get("scope") or ""),
                    "reason": self._truncate_retro_text(str(item.get("reason") or ""), 160),
                }
                for item in list(payload.get("scheduled_rechecks") or [])[:3]
                if isinstance(item, dict)
            ],
        }

    def _retro_news_summary(self, news_events: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
        summary: list[dict[str, Any]] = []
        for item in list(news_events or [])[:limit]:
            if not isinstance(item, dict):
                continue
            summary.append(
                {
                    "news_id": str(item.get("news_id") or item.get("event_id") or ""),
                    "title": self._truncate_retro_text(str(item.get("title") or ""), 160),
                    "summary": self._truncate_retro_text(str(item.get("summary") or ""), 220),
                    "severity": str(item.get("severity") or item.get("impact_level") or ""),
                    "published_at": str(item.get("published_at") or item.get("event_time_utc") or ""),
                }
            )
        return summary

    @staticmethod
    def _retro_execution_context_summary(execution_contexts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        summary: list[dict[str, Any]] = []
        for item in list(execution_contexts or []):
            if not isinstance(item, dict):
                continue
            target = dict(item.get("target") or {})
            execution_summary = dict(item.get("execution_summary") or {})
            market_snapshot = dict(item.get("market_snapshot") or {})
            summary.append(
                {
                    "coin": str(item.get("coin") or ""),
                    "product_id": str(item.get("product_id") or ""),
                    "target_state": str(target.get("state") or ""),
                    "direction": str(target.get("direction") or ""),
                    "target_exposure_band_pct": list(target.get("target_exposure_band_pct") or []),
                    "rt_discretion_band_pct": target.get("rt_discretion_band_pct"),
                    "current_position_share_pct_of_exposure_budget": item.get("current_position_share_pct_of_exposure_budget"),
                    "mark_price": str(market_snapshot.get("mark_price") or ""),
                    "trading_status": str(market_snapshot.get("trading_status") or ""),
                    "execution_summary": execution_summary,
                }
            )
        return summary

    def _retro_macro_memory_summary(self, macro_memory: list[dict[str, Any]]) -> list[dict[str, Any]]:
        summary: list[dict[str, Any]] = []
        for item in list(macro_memory or [])[:5]:
            if not isinstance(item, dict):
                continue
            summary.append(
                {
                    "memory_day_utc": str(item.get("memory_day_utc") or ""),
                    "summary": self._truncate_retro_text(str(item.get("summary") or ""), 220),
                    "event_count": len(list(item.get("event_ids") or [])),
                }
            )
        return summary

    @staticmethod
    def _truncate_retro_text(text: str, limit: int) -> str:
        value = text.strip()
        if len(value) <= limit:
            return value
        return f"{value[: max(0, limit - 1)].rstrip()}…"

    def _run_agent_task_with_retry(self, *, task: AgentTask) -> AgentReply:
        runner = self._runner_for_role(task.agent_role)
        reply = runner.run(task)
        if reply.status != "needs_escalation" or not self._should_retry_after_session_reset(
            task=task,
            meta=reply.meta,
        ):
            return reply
        reset_result = self.reset_agent_session(
            agent_role=task.agent_role,
            session_id=str(task.session_id or self.session_id_for_role(task.agent_role)),
            reset_command="/new",
        )
        if not bool(reset_result.get("success")):
            return reply
        retried = runner.run(
            AgentTask(
                task_id=new_id("task"),
                agent_role=task.agent_role,
                task_kind=task.task_kind,
                input_id=task.input_id,
                trace_id=task.trace_id,
                session_id=task.session_id,
                reply_contract=task.reply_contract,
                payload=task.payload,
            )
        )
        retried.meta["session_reset_retry"] = reset_result
        return retried

    def validate_submission(
        self,
        *,
        submission_kind: str,
        agent_role: str,
        trace_id: str,
        payload: dict[str, Any],
    ) -> ValidatedSubmissionEnvelope:
        model_cls: type[StrategySubmission | ExecutionSubmission | NewsSubmission | MacroBriefSubmission]
        if submission_kind == "strategy":
            model_cls = StrategySubmission
        elif submission_kind == "execution":
            model_cls = ExecutionSubmission
        elif submission_kind == "news":
            model_cls = NewsSubmission
        elif submission_kind == "macro_brief":
            model_cls = MacroBriefSubmission
        else:  # pragma: no cover - defensive
            raise ValueError(f"unsupported submission kind: {submission_kind}")
        schema_ref, prompt_ref = self._submission_contract(submission_kind)
        if submission_kind == "execution" and isinstance(payload.get("execution"), dict) and "decisions" not in payload:
            raise SubmissionValidationError(
                schema_ref=schema_ref,
                prompt_ref=prompt_ref,
                errors=[
                    (
                        "legacy execution wrapper detected: submit root-level "
                        "`decisions[]`; do not wrap the batch under an `execution` object"
                    )
                ],
            )
        try:
            submission = model_cls.model_validate(payload)
        except Exception as exc:
            raise SubmissionValidationError(
                schema_ref=schema_ref,
                prompt_ref=prompt_ref,
                errors=[str(exc)],
            ) from exc
        return ValidatedSubmissionEnvelope(
            envelope_id=new_id("env"),
            submission_kind=submission_kind,
            trace_id=trace_id,
            agent_role=agent_role,
            schema_ref=schema_ref,
            prompt_ref=prompt_ref,
            payload=submission.model_dump(mode="json"),
        )

    def _run_submission_with_retry(
        self,
        *,
        trace_id: str,
        runtime_input: AgentRuntimeInput,
        submission_kind: str,
        agent_role: str,
        task_kind: str,
        runner,
    ) -> ValidatedSubmissionEnvelope:
        session_id = self.session_id_for_role(agent_role)
        task = AgentTask(
            task_id=new_id("task"),
            agent_role=agent_role,
            task_kind=task_kind,
            input_id=runtime_input.input_id,
            trace_id=trace_id,
            session_id=session_id,
            payload=runtime_input.payload,
        )
        reply = runner.run(task)
        if reply.status == "needs_escalation" and self._should_retry_after_session_reset(
            task=task,
            meta=reply.meta,
        ):
            reset_result = self.reset_agent_session(agent_role=agent_role, session_id=session_id, reset_command="/new")
            if bool(reset_result.get("success")):
                reply = runner.run(
                    AgentTask(
                        task_id=new_id("task"),
                        agent_role=agent_role,
                        task_kind=task_kind,
                        input_id=runtime_input.input_id,
                        trace_id=trace_id,
                        session_id=session_id,
                        payload=runtime_input.payload,
                    )
                )
                reply.meta["session_reset_retry"] = reset_result
        if reply.status == "needs_escalation":
            raise self._transport_error(
                submission_kind=submission_kind,
                error_kind=str(reply.meta.get("error_kind") or "agent_process_failed"),
                meta=reply.meta,
            )
        try:
            if reply.status == "needs_revision":
                raise SubmissionValidationError(
                    schema_ref=self._submission_contract(submission_kind)[0],
                    prompt_ref=self._submission_contract(submission_kind)[1],
                    errors=[str(reply.meta.get("error_kind") or "agent_invalid_transport_payload")],
                    error_kind=str(reply.meta.get("error_kind") or "agent_invalid_transport_payload"),
                    raw_reply=str(reply.meta.get("stdout") or reply.meta.get("raw") or ""),
                    stderr_summary=str(reply.meta.get("stderr") or ""),
                )
            return self.validate_submission(
                submission_kind=submission_kind,
                agent_role=agent_role,
                trace_id=trace_id,
                payload=reply.payload,
            )
        except SubmissionValidationError as exc:
            repair_payload = self._build_repair_payload(
                runtime_input=runtime_input.payload,
                submission_kind=submission_kind,
                schema_ref=exc.schema_ref,
                prompt_ref=exc.prompt_ref,
                errors=exc.errors,
                previous_reply=reply.meta.get("stdout"),
            )
            repair_reply = runner.run(
                AgentTask(
                    task_id=new_id("task"),
                    agent_role=agent_role,
                    task_kind=task_kind,
                    input_id=runtime_input.input_id,
                    trace_id=trace_id,
                    session_id=session_id,
                    reply_contract="repair_json_only",
                    payload=repair_payload,
                )
            )
            if repair_reply.status == "needs_escalation":
                raise self._transport_error(
                    submission_kind=submission_kind,
                    error_kind=str(repair_reply.meta.get("error_kind") or "agent_process_failed"),
                    meta=repair_reply.meta,
                ) from exc
            try:
                return self.validate_submission(
                    submission_kind=submission_kind,
                    agent_role=agent_role,
                    trace_id=trace_id,
                    payload=repair_reply.payload,
                )
            except SubmissionValidationError as repair_exc:
                raise SubmissionValidationError(
                    schema_ref=repair_exc.schema_ref,
                    prompt_ref=repair_exc.prompt_ref,
                    errors=repair_exc.errors,
                    error_kind=str(repair_reply.meta.get("error_kind") or repair_exc.error_kind),
                    raw_reply=str(repair_reply.meta.get("stdout") or repair_reply.meta.get("raw") or ""),
                    stderr_summary=str(repair_reply.meta.get("stderr") or ""),
                ) from exc

    def _transport_error(self, *, submission_kind: str, error_kind: str, meta: dict[str, Any]) -> SubmissionValidationError:
        schema_ref, prompt_ref = self._submission_contract(submission_kind)
        return SubmissionValidationError(
            schema_ref=schema_ref,
            prompt_ref=prompt_ref,
            errors=[error_kind],
            error_kind=error_kind,
            raw_reply=str(meta.get("stdout") or meta.get("raw") or ""),
            stderr_summary=str(meta.get("stderr") or ""),
        )

    def _submission_contract(self, submission_kind: str) -> tuple[str, str]:
        if submission_kind == "strategy":
            return self._STRATEGY_SCHEMA_REF, self._STRATEGY_PROMPT_REF
        if submission_kind == "execution":
            return self._EXECUTION_SCHEMA_REF, self._EXECUTION_PROMPT_REF
        if submission_kind == "news":
            return self._NEWS_SCHEMA_REF, self._NEWS_PROMPT_REF
        if submission_kind == "macro_brief":
            return self._MACRO_BRIEF_SCHEMA_REF, self._MACRO_BRIEF_PROMPT_REF
        raise ValueError(f"unsupported submission kind: {submission_kind}")

    @classmethod
    def _chief_retro_error(
        cls,
        *,
        error_kind: str,
        raw_reply: str,
        stderr_summary: str,
        errors: list[str] | None = None,
    ) -> SubmissionValidationError:
        return SubmissionValidationError(
            schema_ref=cls._CHIEF_RETRO_SPEC_REF,
            prompt_ref=cls._CHIEF_RETRO_PROMPT_REF,
            errors=list(errors or [error_kind]),
            error_kind=error_kind,
            raw_reply=raw_reply,
            stderr_summary=stderr_summary,
        )

    @staticmethod
    def _normalize_chief_retro_payload(payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload or {})
        normalized["case_id"] = str(normalized.get("case_id") or "").strip() or None
        normalized["owner_summary"] = str(normalized.get("owner_summary") or "").strip()
        normalized["reset_command"] = str(normalized.get("reset_command") or "/new").strip() or "/new"
        normalized["root_cause_ranking"] = [str(item).strip() for item in list(normalized.get("root_cause_ranking") or []) if str(item).strip()]
        normalized["role_judgements"] = {
            str(key).strip(): str(value).strip()
            for key, value in dict(normalized.get("role_judgements") or {}).items()
            if str(key).strip() and str(value).strip()
        }
        normalized["learning_directives"] = [
            dict(item)
            for item in list(normalized.get("learning_directives") or [])
            if isinstance(item, dict)
        ]
        return normalized

    @staticmethod
    def _normalize_learning_directive_submissions(payload: Any) -> list[dict[str, Any]]:
        directives: list[dict[str, Any]] = []
        for item in list(payload or []):
            if not isinstance(item, dict):
                continue
            agent_role = str(item.get("agent_role") or "").strip()
            directive = str(item.get("directive") or "").strip()
            rationale = str(item.get("rationale") or "").strip()
            if not agent_role or not directive or not rationale:
                continue
            directives.append(
                {
                    "agent_role": agent_role,
                    "directive": directive,
                    "rationale": rationale,
                }
            )
        return directives

    def _materialize_learning_directive_assets(
        self,
        *,
        trace_id: str,
        case_id: str,
        cycle_id: str | None,
        directives: list[dict[str, Any]],
        learning_targets: list[dict[str, Any]],
        source_ref: str,
    ) -> list[dict[str, Any]]:
        if not case_id:
            return []
        targets_by_role = {
            str(item.get("agent_role") or "").strip(): item
            for item in learning_targets
            if isinstance(item, dict)
        }
        assets: list[dict[str, Any]] = []
        for directive in directives:
            agent_role = str(directive.get("agent_role") or "").strip()
            target = targets_by_role.get(agent_role)
            if not agent_role or target is None:
                continue
            assets.append(
                self.memory_assets.materialize_learning_directive(
                    trace_id=trace_id,
                    case_id=case_id,
                    agent_role=agent_role,
                    session_key=str(target.get("session_key") or ""),
                    learning_path=str(target.get("learning_path") or ""),
                    cycle_id=cycle_id,
                    authored_payload={
                        "directive": str(directive.get("directive") or ""),
                        "rationale": str(directive.get("rationale") or ""),
                    },
                    source_ref=source_ref,
                    metadata={"case_id": case_id},
                )
            )
        return assets

    def _resolve_retro_cycle_id(self, *, case_id: str | None) -> str | None:
        if not case_id:
            return None
        retro_case = self.memory_assets.get_retro_case(case_id=case_id)
        if retro_case is None:
            return None
        return str(retro_case.get("cycle_id") or "").strip() or None

    @staticmethod
    def _normalize_retro_learning_results(payload: Any) -> list[dict[str, Any]]:
        if payload is None:
            return []
        if isinstance(payload, list):
            return [dict(item) for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            values = list(payload.values())
            if values and all(isinstance(item, dict) for item in values):
                normalized: list[dict[str, Any]] = []
                for role, item in payload.items():
                    record = dict(item)
                    record.setdefault("agent_role", str(role))
                    normalized.append(record)
                return normalized
            return [dict(payload)]
        return []

    @staticmethod
    def _validate_retro_learning_ack(
        payload: dict[str, Any],
        *,
        agent_role: str,
        learning_path: str,
    ) -> RetroLearningAck | None:
        normalized = dict(payload or {})
        normalized["agent_role"] = str(normalized.get("agent_role") or agent_role).strip() or agent_role
        normalized["learning_path"] = str(normalized.get("learning_path") or learning_path).strip() or learning_path
        normalized["learning_summary"] = str(normalized.get("learning_summary") or "").strip()
        normalized["learning_updated"] = bool(normalized.get("learning_updated"))
        if normalized["agent_role"] != agent_role or normalized["learning_path"] != learning_path:
            return None
        if not normalized["learning_updated"] or not normalized["learning_summary"]:
            return None
        try:
            return RetroLearningAck.model_validate(normalized)
        except Exception:
            return None

    def _capture_retro_learning_targets(self) -> list[dict[str, Any]]:
        return [
            {
                "agent_role": agent_role,
                "session_key": f"agent:{self.agent_name_by_role.get(agent_role) or self._DEFAULT_AGENT_NAME_BY_ROLE.get(agent_role, agent_role)}:main",
                "learning_path": self.learning_path_by_role.get(agent_role) or self._DEFAULT_LEARNING_PATH_BY_ROLE.get(agent_role, ""),
                "baseline": self._learning_file_fingerprint(
                    self.learning_path_by_role.get(agent_role) or self._DEFAULT_LEARNING_PATH_BY_ROLE.get(agent_role, "")
                ),
            }
            for agent_role in self._RETRO_LEARNING_ROLES
        ]

    def _validate_retro_learning_results(
        self,
        payload_results: list[dict[str, Any]],
        *,
        learning_targets: list[dict[str, Any]],
    ) -> list[RetroLearningAck]:
        errors: list[str] = []
        validated: list[RetroLearningAck] = []
        results_by_role = {
            str(item.get("agent_role") or "").strip(): item
            for item in list(payload_results or [])
            if isinstance(item, dict)
        }
        for target in learning_targets:
            agent_role = str(target["agent_role"])
            learning_path = str(target["learning_path"])
            result_payload = results_by_role.get(agent_role)
            if result_payload is None:
                errors.append(f"learning_missing:{agent_role}")
                continue
            learning_ack = self._validate_retro_learning_ack(
                result_payload,
                agent_role=agent_role,
                learning_path=learning_path,
            )
            if learning_ack is None:
                errors.append(f"learning_result_invalid:{agent_role}")
                continue
            current_state = self._learning_file_fingerprint(learning_path)
            if not self._learning_file_changed(
                baseline=dict(target.get("baseline") or {}),
                current_state=current_state,
            ):
                errors.append(f"learning_file_unchanged:{agent_role}")
                continue
            validated.append(learning_ack)
        if errors:
            raise self._chief_retro_error(
                error_kind="retro_learning_verification_failed",
                raw_reply="",
                stderr_summary="",
                errors=errors,
            )
        return validated

    @staticmethod
    def _learning_file_fingerprint(learning_path: str) -> dict[str, Any]:
        path = Path(learning_path)
        if not path.exists():
            return {
                "exists": False,
                "mtime_ns": None,
                "size_bytes": 0,
                "content_sha256": None,
            }
        try:
            content = path.read_bytes()
        except OSError:
            content = b""
        stat = path.stat()
        return {
            "exists": True,
            "mtime_ns": stat.st_mtime_ns,
            "size_bytes": stat.st_size,
            "content_sha256": hashlib.sha256(content).hexdigest(),
        }

    @staticmethod
    def _learning_file_changed(*, baseline: dict[str, Any], current_state: dict[str, Any]) -> bool:
        if not bool(current_state.get("exists")) or int(current_state.get("size_bytes") or 0) <= 0:
            return False
        if not bool(baseline.get("exists")):
            return True
        return any(
            current_state.get(key) != baseline.get(key)
            for key in ("mtime_ns", "size_bytes", "content_sha256")
        )

    def _runner_for_role(self, agent_role: str) -> AgentRunner:
        if agent_role == "pm":
            return self.pm_runner
        if agent_role == "risk_trader":
            return self.risk_runner
        if agent_role == "macro_event_analyst":
            return self.macro_runner
        if agent_role == "crypto_chief":
            return self.chief_runner
        raise ValueError(f"unsupported agent role: {agent_role}")

    @staticmethod
    def _build_repair_payload(
        *,
        runtime_input: dict[str, Any],
        submission_kind: str,
        schema_ref: str,
        prompt_ref: str,
        errors: list[str],
        previous_reply: object,
    ) -> dict[str, Any]:
        return {
            "mode": "schema_repair",
            "submission_kind": submission_kind,
            "instruction": "上一版正式提交没有通过校验。现在只返回一个纯 JSON 对象，不要使用 markdown 代码块，也不要附带解释。",
            "schema_ref": schema_ref,
            "prompt_ref": prompt_ref,
            "validation_errors": list(errors),
            "previous_reply": previous_reply,
            "original_runtime_input": runtime_input,
        }

    def request_execution_decisions(
        self,
        *,
        trace_id: str,
        runtime_input: AgentRuntimeInput,
        execution_contexts: list[Any],
    ) -> list[ExecutionDecision]:
        payload = dict(runtime_input.payload)
        payload["execution_contexts"] = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
            for item in execution_contexts
        ]
        envelope = self.run_rt_submission(
            trace_id=trace_id,
            runtime_input=AgentRuntimeInput(
                input_id=runtime_input.input_id,
                agent_role=runtime_input.agent_role,
                task_kind=runtime_input.task_kind,
                payload=payload,
            ),
        )
        decisions: list[ExecutionDecision] = []
        execution_submission = ExecutionSubmission.model_validate(envelope.payload)
        for item in execution_submission.decisions:
            decisions.append(
                ExecutionDecision(
                    decision_id=execution_submission.decision_id,
                    strategy_version=execution_submission.strategy_id or "unknown",
                    context_id=new_id("execctx"),
                    product_id=f"{item.symbol}-PERP-INTX",
                    coin=item.symbol,
                    action=item.action,
                    side=item.direction or ("flat" if item.action in {"wait", "hold"} else "long"),
                    size_pct_of_exposure_budget=item.size_pct_of_exposure_budget,
                    urgency=item.urgency,
                    valid_for_minutes=item.valid_for_minutes,
                    reason=item.reason,
                    priority=item.priority,
                )
            )
        return decisions

    def build_submission_event(self, *, trace_id: str, envelope: ValidatedSubmissionEnvelope):
        return EventFactory.build(
            trace_id=trace_id,
            event_type=EVENT_SUBMISSION_VALIDATED,
            source_module=MODULE_NAME,
            entity_type="validated_submission",
            entity_id=envelope.envelope_id,
            payload=envelope.model_dump(mode="json"),
        )

    def build_submission_error_event(self, *, trace_id: str, agent_role: str, error: SubmissionValidationError):
        return EventFactory.build(
            trace_id=trace_id,
            event_type=EVENT_SUBMISSION_REJECTED,
            source_module=MODULE_NAME,
            entity_type="submission_error",
            entity_id=new_id("submission_error"),
            payload={
                "agent_role": agent_role,
                "schema_ref": error.schema_ref,
                "prompt_ref": error.prompt_ref,
                "errors": error.errors,
                "error_kind": error.error_kind,
                "raw_reply": error.raw_reply,
                "stderr_summary": error.stderr_summary,
            },
        )

    def build_session_reset_event(
        self,
        *,
        trace_id: str,
        agent_role: str,
        session_id: str,
        result: dict[str, object] | None = None,
    ):
        return EventFactory.build(
            trace_id=trace_id,
            event_type=EVENT_AGENT_SESSION_RESET,
            source_module=MODULE_NAME,
            entity_type="agent_session",
            entity_id=session_id,
            payload={
                "agent_role": agent_role,
                "session_id": session_id,
                "reset_command": "/new",
                "result": result or {},
            },
        )

    def reset_agent_session(self, *, agent_role: str, session_id: str, reset_command: str = "/new") -> dict[str, object]:
        if self.session_controller is None:
            return {
                "agent_role": agent_role,
                "session_id": session_id,
                "reset_command": reset_command,
                "success": False,
                "error": "session_controller_not_configured",
            }
        return self.session_controller.reset(agent_role=agent_role, session_id=session_id, reset_command=reset_command)

    @staticmethod
    def _forecast_payload(forecasts: dict[str, CoinForecast]) -> dict[str, dict[str, dict[str, float | str]]]:
        payload: dict[str, dict[str, dict[str, float | str]]] = {}
        for coin, forecast in forecasts.items():
            per_coin: dict[str, dict[str, float | str]] = {}
            for horizon in ("1h", "4h", "12h"):
                signal = forecast.horizons.get(horizon)
                if signal is None:
                    continue
                per_coin[horizon] = {"side": signal.side, "confidence": round(float(signal.confidence), 4)}
            payload[coin] = per_coin
        return payload

    @staticmethod
    def _policy_payload(policy: GuardDecision) -> dict[str, object]:
        payload = policy.model_dump(mode="json")
        diagnostics = payload.get("diagnostics")
        if isinstance(diagnostics, dict):
            diagnostics.pop("ignored_horizons", None)
        return payload

    @staticmethod
    def default_recheck_at(hours: int = 4) -> datetime:
        return datetime.now(UTC) + timedelta(hours=hours)

    @staticmethod
    def today_utc() -> str:
        return date.today().isoformat()

    @classmethod
    def _compact_market_payload(cls, market: DataIngestBundle, *, agent_role: str) -> dict[str, Any]:
        payload = cls._strip_raw_fields(market.model_dump(mode="json"))
        price_point_limit = cls._PRICE_POINT_LIMIT_BY_ROLE.get(agent_role, 12)
        execution_limit = cls._EXECUTION_SAMPLE_LIMIT_BY_ROLE.get(agent_role, 3)
        payload["market_context"] = cls._compact_market_context(payload.get("market_context", {}), point_limit=price_point_limit)
        payload["product_metadata"] = cls._compact_product_metadata(payload.get("product_metadata", {}))
        payload["accounts"] = cls._compact_accounts(payload.get("accounts", {}))
        payload["portfolio"] = cls._compact_portfolio(payload.get("portfolio", {}))
        if execution_limit <= 0:
            payload.pop("execution_history", None)
        else:
            payload["execution_history"] = cls._compact_execution_history(
                payload.get("execution_history", {}),
                sample_limit=execution_limit,
            )
        if agent_role == "macro_event_analyst":
            payload.pop("accounts", None)
            payload.pop("portfolio", None)
        return payload

    @classmethod
    def _compact_strategy_payload(cls, payload: dict[str, Any] | None, *, agent_role: str) -> dict[str, Any]:
        if not payload:
            return {}
        keep_keys_by_role = {
            "risk_trader": {
                "strategy_id",
                "strategy_version",
                "strategy_day_utc",
                "generated_at_utc",
                "trigger_type",
                "revision_number",
                "portfolio_mode",
                "target_gross_exposure_band_pct",
                "portfolio_thesis",
                "portfolio_invalidation",
                "flip_triggers",
                "change_summary",
                "targets",
                "internal_reasoning_only",
            },
            "crypto_chief": {
                "strategy_id",
                "strategy_day_utc",
                "generated_at_utc",
                "trigger_type",
                "supersedes_strategy_id",
                "revision_number",
                "portfolio_mode",
                "target_gross_exposure_band_pct",
                "portfolio_thesis",
                "portfolio_invalidation",
                "flip_triggers",
                "change_summary",
                "targets",
                "internal_reasoning_only",
                "scheduled_rechecks",
            },
            "macro_event_analyst": {
                "strategy_id",
                "strategy_day_utc",
                "generated_at_utc",
                "revision_number",
                "portfolio_mode",
                "target_gross_exposure_band_pct",
                "portfolio_thesis",
                "portfolio_invalidation",
                "flip_triggers",
                "change_summary",
                "targets",
                "internal_reasoning_only",
            },
        }
        keep_keys = keep_keys_by_role.get(agent_role)
        if not keep_keys:
            return dict(payload)
        return {key: value for key, value in payload.items() if key in keep_keys}

    @classmethod
    def _compact_execution_contexts(cls, contexts: list[Any], *, agent_role: str) -> list[dict[str, Any]]:
        compacted: list[dict[str, Any]] = []
        for item in contexts:
            payload = item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item or {})
            current_position_share_pct_of_exposure_budget = payload.get("current_position_share_pct_of_exposure_budget")
            if current_position_share_pct_of_exposure_budget is None:
                current_position_share_pct_of_exposure_budget = payload.get("current_position_share_pct")
            if current_position_share_pct_of_exposure_budget is None:
                current_position_share_pct_of_exposure_budget = dict(payload.get("account_snapshot") or {}).get(
                    "current_position_share_pct_of_exposure_budget"
                )
            if current_position_share_pct_of_exposure_budget is None:
                current_position_share_pct_of_exposure_budget = dict(payload.get("account_snapshot") or {}).get(
                    "current_position_share_pct"
                )
            if agent_role == "risk_trader":
                compacted.append(
                    {
                        "context_id": payload.get("context_id"),
                        "strategy_id": payload.get("strategy_id"),
                        "coin": payload.get("coin"),
                        "product_id": payload.get("product_id"),
                        "target": cls._compact_strategy_target(payload.get("target")),
                        "current_position_share_pct_of_exposure_budget": current_position_share_pct_of_exposure_budget,
                        "market_snapshot": cls._compact_execution_market_snapshot(payload.get("market_snapshot")),
                        "account_snapshot": cls._compact_execution_account_snapshot(payload.get("account_snapshot")),
                        "product_metadata": cls._compact_execution_product_metadata(payload.get("product_metadata")),
                        "execution_summary": cls._compact_execution_summary(payload.get("execution_history")),
                    }
                )
                continue
            compacted.append(payload)
        return compacted

    @staticmethod
    def _compact_strategy_target(payload: dict[str, Any] | None) -> dict[str, Any]:
        keep_keys = {
            "symbol",
            "state",
            "direction",
            "target_exposure_band_pct",
            "rt_discretion_band_pct",
            "priority",
        }
        return {
            key: value for key, value in dict(payload or {}).items() if key in keep_keys
        }

    @staticmethod
    def _compact_execution_market_snapshot(payload: dict[str, Any] | None) -> dict[str, Any]:
        keep_keys = {
            "product_id",
            "mark_price",
            "index_price",
            "best_bid",
            "best_ask",
            "spread_bps",
            "funding_rate",
            "premium",
            "open_interest",
            "day_notional_volume",
            "day_price_change_pct",
            "trading_status",
            "captured_at",
        }
        return {key: value for key, value in dict(payload or {}).items() if key in keep_keys}

    @staticmethod
    def _compact_execution_account_snapshot(payload: dict[str, Any] | None) -> dict[str, Any]:
        keep_keys = {
            "coin",
            "current_side",
            "current_notional_usd",
            "current_quantity",
            "current_leverage",
            "entry_price",
            "unrealized_pnl_usd",
            "liquidation_price",
            "available_equity_usd",
            "captured_at",
        }
        return {key: value for key, value in dict(payload or {}).items() if key in keep_keys}

    @staticmethod
    def _compact_execution_product_metadata(payload: dict[str, Any] | None) -> dict[str, Any]:
        keep_keys = {
            "coin",
            "product_id",
            "tick_size",
            "size_increment",
            "min_size",
            "min_notional",
            "max_leverage",
            "trading_status",
            "trading_disabled",
            "cancel_only",
            "limit_only",
            "post_only",
        }
        return {key: value for key, value in dict(payload or {}).items() if key in keep_keys}

    @staticmethod
    def _compact_execution_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
        history = dict(payload or {})
        summary = dict(history.get("summary") or {})
        if not summary:
            summary = {
                "recent_order_count": len(history.get("recent_orders", [])),
                "recent_fill_count": len(history.get("recent_fills", [])),
                "open_order_count": len(history.get("open_orders", [])),
                "failure_count": len(history.get("failure_sources", [])),
            }
        return summary

    @staticmethod
    def _compact_news_events(events: list[NewsDigestEvent], *, limit: int) -> list[dict[str, Any]]:
        severity_rank = {"critical": 3, "high": 2, "medium": 1, "low": 0}

        def _sort_key(item: NewsDigestEvent) -> tuple[int, datetime]:
            severity = str(getattr(item, "severity", "") or "").lower()
            published_at = getattr(item, "published_at", None) or datetime.min.replace(tzinfo=UTC)
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=UTC)
            return (severity_rank.get(severity, -1), published_at.astimezone(UTC))

        compacted: list[dict[str, Any]] = []
        ranked_events = sorted(list(events or []), key=_sort_key, reverse=True)
        for item in ranked_events[:limit]:
            payload = item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item or {})
            compacted.append(
                {
                    "news_id": payload.get("news_id"),
                    "source": payload.get("source"),
                    "title": payload.get("title"),
                    "summary": payload.get("summary"),
                    "severity": payload.get("severity"),
                    "published_at": payload.get("published_at"),
                    "tags": payload.get("tags") or [],
                }
            )
        return compacted

    @staticmethod
    def _should_retry_after_session_reset(*, task: AgentTask, meta: dict[str, Any]) -> bool:
        if str(meta.get("error_kind") or "") == "agent_timeout":
            if task.task_kind == "retro_brief":
                return True
            if task.agent_role in {"risk_trader", "crypto_chief"}:
                return True
        haystack = " ".join(
            str(meta.get(key) or "")
            for key in ("stderr", "stdout", "raw")
        ).lower()
        markers = (
            "range of input length",
            "input length should be",
            "maximum context length",
            "too many context tokens",
            "context length exceeded",
        )
        return any(marker in haystack for marker in markers)

    @classmethod
    def _strip_raw_fields(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: cls._strip_raw_fields(nested)
                for key, nested in value.items()
                if key != "raw"
            }
        if isinstance(value, list):
            return [cls._strip_raw_fields(item) for item in value]
        return value

    @classmethod
    def _compact_market_context(cls, payload: dict[str, Any], *, point_limit: int) -> dict[str, Any]:
        compacted: dict[str, Any] = {}
        for coin, context in payload.items():
            context_payload = dict(context)
            compressed = {}
            for window, series in (context_payload.get("compressed_price_series") or {}).items():
                series_payload = dict(series)
                points = list(series_payload.get("points") or [])
                if point_limit > 0 and len(points) > point_limit:
                    series_payload["points"] = points[-point_limit:]
                compressed[window] = series_payload
            context_payload["compressed_price_series"] = compressed
            compacted[coin] = context_payload
        return compacted

    @staticmethod
    def _compact_product_metadata(payload: dict[str, Any]) -> dict[str, Any]:
        keep_keys = {
            "coin",
            "product_id",
            "tick_size",
            "size_increment",
            "min_size",
            "min_notional",
            "max_leverage",
            "trading_status",
            "trading_disabled",
            "cancel_only",
            "limit_only",
            "post_only",
            "captured_at",
        }
        return {
            coin: {key: value for key, value in snapshot.items() if key in keep_keys}
            for coin, snapshot in payload.items()
        }

    @staticmethod
    def _compact_accounts(payload: dict[str, Any]) -> dict[str, Any]:
        keep_keys = {
            "coin",
            "total_equity_usd",
            "available_equity_usd",
            "current_side",
            "current_notional_usd",
            "current_leverage",
            "current_quantity",
            "entry_price",
            "unrealized_pnl_usd",
            "liquidation_price",
            "captured_at",
        }
        return {
            coin: {key: value for key, value in snapshot.items() if key in keep_keys}
            for coin, snapshot in payload.items()
        }

    @staticmethod
    def _compact_portfolio(payload: dict[str, Any]) -> dict[str, Any]:
        keep_keys = {
            "starting_equity_usd",
            "realized_pnl_usd",
            "unrealized_pnl_usd",
            "total_equity_usd",
            "available_equity_usd",
            "total_exposure_usd",
            "open_order_hold_usd",
            "positions",
            "captured_at",
        }
        position_keys = {
            "coin",
            "side",
            "quantity",
            "notional_usd",
            "leverage",
            "entry_price",
            "unrealized_pnl_usd",
            "position_share_pct_of_exposure_budget",
            "opened_at",
        }
        compacted = {key: value for key, value in payload.items() if key in keep_keys}
        compacted["positions"] = [
            {key: value for key, value in position.items() if key in position_keys}
            for position in payload.get("positions", [])
        ]
        return compacted

    @classmethod
    def _compact_execution_history(cls, payload: dict[str, Any], *, sample_limit: int) -> dict[str, Any]:
        compacted: dict[str, Any] = {}
        for coin, history in payload.items():
            compacted[coin] = {
                "coin": history.get("coin"),
                "product_id": history.get("product_id"),
                "captured_at": history.get("captured_at"),
                "recent_orders": cls._sample_records(
                    history.get("recent_orders", []),
                    sample_limit=sample_limit,
                    keep_keys={
                        "order_id",
                        "product_id",
                        "side",
                        "status",
                        "order_type",
                        "created_time",
                        "filled_size",
                        "average_filled_price",
                        "filled_value",
                        "reject_reason",
                        "reject_message",
                        "outstanding_hold_amount",
                        "leverage",
                        "last_fill_time",
                        "last_update_time",
                    },
                ),
                "recent_fills": cls._sample_records(
                    history.get("recent_fills", []),
                    sample_limit=sample_limit,
                    keep_keys={
                        "trade_id",
                        "order_id",
                        "trade_time",
                        "trade_type",
                        "price",
                        "size",
                        "commission",
                        "product_id",
                        "side",
                        "liquidity_indicator",
                    },
                ),
                "open_orders": cls._sample_records(
                    history.get("open_orders", []),
                    sample_limit=sample_limit,
                    keep_keys={
                        "order_id",
                        "status",
                        "side",
                        "order_type",
                        "notional_usd",
                        "limit_price",
                        "base_size",
                        "created_at",
                    },
                ),
                "failure_sources": cls._sample_records(
                    history.get("failure_sources", []),
                    sample_limit=sample_limit,
                    keep_keys={
                        "source",
                        "reason",
                        "message",
                        "captured_at",
                        "symbol",
                        "order_id",
                    },
                ),
                "summary": {
                    "recent_order_count": len(history.get("recent_orders", [])),
                    "recent_fill_count": len(history.get("recent_fills", [])),
                    "open_order_count": len(history.get("open_orders", [])),
                    "failure_count": len(history.get("failure_sources", [])),
                },
            }
        return compacted

    @staticmethod
    def _sample_records(records: list[Any], *, sample_limit: int, keep_keys: set[str]) -> list[dict[str, Any]]:
        sampled: list[dict[str, Any]] = []
        for record in list(records)[-sample_limit:]:
            if isinstance(record, dict):
                sampled.append({key: value for key, value in record.items() if key in keep_keys})
        return sampled

    _SESSION_ID_BY_ROLE = {
        "pm": "pm-session",
        "risk_trader": "risk-trader-session",
        "macro_event_analyst": "macro-event-analyst-session",
        "crypto_chief": "crypto-chief-session",
    }
    _DEFAULT_AGENT_NAME_BY_ROLE = {
        "pm": "pm",
        "risk_trader": "risk-trader",
        "macro_event_analyst": "macro-event-analyst",
        "crypto_chief": "crypto-chief",
    }
    _DEFAULT_LEARNING_PATH_BY_ROLE = {
        "pm": str(Path.home() / ".openclaw" / "workspace-pm" / ".learnings" / "pm.md"),
        "risk_trader": str(Path.home() / ".openclaw" / "workspace-risk-trader" / ".learnings" / "risk_trader.md"),
        "macro_event_analyst": str(
            Path.home() / ".openclaw" / "workspace-macro-event-analyst" / ".learnings" / "macro_event_analyst.md"
        ),
        "crypto_chief": str(Path.home() / ".openclaw" / "workspace-crypto-chief" / ".learnings" / "crypto_chief.md"),
    }
    _RETRO_BRIEF_ROLES = (
        "pm",
        "risk_trader",
        "macro_event_analyst",
    )
    _RETRO_LEARNING_ROLES = (
        "pm",
        "risk_trader",
        "macro_event_analyst",
        "crypto_chief",
    )
    _PRICE_POINT_LIMIT_BY_ROLE = {
        "pm": 12,
        "risk_trader": 8,
        "macro_event_analyst": 8,
        "crypto_chief": 8,
    }
    _EXECUTION_SAMPLE_LIMIT_BY_ROLE = {
        "pm": 3,
        "risk_trader": 2,
        "macro_event_analyst": 0,
        "crypto_chief": 3,
    }

    def _resolve_openclaw_main_session_id(self, agent_role: str) -> str | None:
        agent_name = self.agent_name_by_role.get(agent_role)
        if not agent_name:
            return None
        store_path = Path.home() / ".openclaw" / "agents" / agent_name / "sessions" / "sessions.json"
        if not store_path.exists():
            return None
        try:
            payload = json.loads(store_path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        entry = payload.get(f"agent:{agent_name}:main")
        if not isinstance(entry, dict):
            return None
        session_id = entry.get("sessionId")
        return session_id if isinstance(session_id, str) and session_id else None
