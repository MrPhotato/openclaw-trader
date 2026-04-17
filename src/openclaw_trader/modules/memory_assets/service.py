from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ...shared.protocols import EventEnvelope, EventFactory
from ...shared.utils import new_id
from .events import EVENT_NOTIFICATION_RECORDED, EVENT_PARAMETER_CHANGED, EVENT_STATE_SNAPSHOT_CAPTURED, MODULE_NAME
from .models import (
    AgentSessionState,
    LearningDirectiveAsset,
    NewsSubmissionAsset,
    NotificationResult,
    OverviewQueryView,
    ReplayQueryView,
    RetroBriefAsset,
    RetroCaseAsset,
    RetroCycleStateAsset,
    RTTacticalMapAsset,
    RuntimeBridgeState,
    StateSnapshot,
    StrategyAsset,
    WorkflowStateRef,
)
from .repository import MemoryAssetsRepository


class MemoryAssetsService:
    def __init__(self, repository: MemoryAssetsRepository) -> None:
        self.repository = repository

    def save_workflow(self, command_id: str, workflow: WorkflowStateRef, payload: dict) -> None:
        self.repository.save_workflow(command_id, workflow, payload)

    def get_workflow_by_command(self, command_id: str) -> WorkflowStateRef | None:
        return self.repository.get_workflow_by_command(command_id)

    def get_workflow(self, trace_id: str) -> WorkflowStateRef | None:
        return self.repository.get_workflow(trace_id)

    def append_event(self, envelope: EventEnvelope) -> None:
        self.repository.append_event(envelope)

    def query_events(self, *, trace_id: str | None = None, module: str | None = None, limit: int = 200) -> list[dict]:
        return self.repository.query_events(trace_id=trace_id, module=module, limit=limit)

    def save_strategy(self, strategy_version: str, trace_id: str, payload: dict) -> None:
        self.repository.save_strategy(strategy_version, trace_id, payload)

    def materialize_strategy_asset(
        self,
        *,
        trace_id: str,
        authored_payload: dict,
        trigger_type: str,
        actor_role: str = "pm",
        source_ref: str | None = None,
    ) -> dict:
        now = datetime.now(UTC)
        previous_strategy = self.latest_strategy()
        previous_payload = previous_strategy["payload"] if previous_strategy else {}
        previous_id = str(previous_payload.get("strategy_id") or "").strip() or None
        previous_revision = previous_payload.get("revision_number") if isinstance(previous_payload, dict) else None
        try:
            previous_revision_number = int(previous_revision)
        except (TypeError, ValueError):
            previous_revision_number = 0

        canonical_payload = dict(authored_payload)
        canonical_payload.update(
            {
                "strategy_id": new_id("strategy"),
                "strategy_day_utc": now.date().isoformat(),
                "generated_at_utc": now.isoformat(),
                "trigger_type": trigger_type,
                "supersedes_strategy_id": previous_id,
                "revision_number": previous_revision_number + 1 if previous_id else 1,
            }
        )
        canonical_payload = StrategyAsset.model_validate(canonical_payload).model_dump(mode="json")
        self.save_asset(
            asset_type="strategy",
            payload=canonical_payload,
            trace_id=trace_id,
            actor_role=actor_role,
            group_key=str(canonical_payload["strategy_day_utc"]),
            source_ref=source_ref,
            metadata={"trigger_type": trigger_type},
        )
        self.save_strategy(str(canonical_payload["strategy_id"]), trace_id, canonical_payload)
        return canonical_payload

    def materialize_news_submission(
        self,
        *,
        trace_id: str,
        authored_payload: dict,
        actor_role: str = "macro_event_analyst",
        source_ref: str | None = None,
    ) -> dict:
        now = datetime.now(UTC)
        canonical_payload = dict(authored_payload)
        canonical_payload.update(
            {
                "submission_id": new_id("news"),
                "generated_at_utc": now.isoformat(),
            }
        )
        canonical_payload = NewsSubmissionAsset.model_validate(canonical_payload).model_dump(mode="json")
        self.save_asset(
            asset_type="news_submission",
            payload=canonical_payload,
            trace_id=trace_id,
            actor_role=actor_role,
            group_key=str(canonical_payload["submission_id"]),
            source_ref=source_ref,
        )
        return canonical_payload

    def latest_strategy(self) -> dict | None:
        return self.repository.latest_strategy()

    def get_latest_strategy(self) -> dict | None:
        latest_asset = self.latest_asset(asset_type="strategy")
        if latest_asset is not None:
            return latest_asset
        return self.latest_strategy()

    def save_portfolio(self, trace_id: str, payload: dict) -> None:
        self.repository.save_portfolio(trace_id, payload)

    def latest_portfolio(self) -> dict | None:
        return self.repository.latest_portfolio()

    def recent_portfolios(self, *, limit: int = 24) -> list[dict]:
        return self.repository.recent_portfolios(limit=limit)

    def portfolio_equity_timeseries(self, *, since: str, bucket_minutes: int = 15) -> list[dict]:
        return self.repository.portfolio_equity_timeseries(since=since, bucket_minutes=bucket_minutes)

    def save_asset(
        self,
        *,
        asset_type: str,
        payload: dict,
        trace_id: str | None = None,
        actor_role: str | None = None,
        group_key: str | None = None,
        source_ref: str | None = None,
        metadata: dict | None = None,
        asset_id: str | None = None,
    ) -> dict:
        record_id = asset_id or new_id(asset_type.replace(".", "_"))
        record = {
            "asset_id": record_id,
            "asset_type": asset_type,
            "trace_id": trace_id,
            "actor_role": actor_role,
            "group_key": group_key,
            "source_ref": source_ref,
            "payload": payload,
            "metadata": metadata or {},
            "created_at": datetime.now(UTC).isoformat(),
        }
        self.repository.save_asset(
            asset_id=record_id,
            asset_type=asset_type,
            trace_id=trace_id,
            actor_role=actor_role,
            group_key=group_key,
            source_ref=source_ref,
            payload=payload,
            metadata=metadata or {},
        )
        return record

    def get_asset(self, asset_id: str) -> dict | None:
        return self.repository.get_asset(asset_id)

    def latest_asset(self, *, asset_type: str, actor_role: str | None = None) -> dict | None:
        return self.repository.latest_asset(asset_type=asset_type, actor_role=actor_role)

    def latest_runtime_bridge_state_asset(self) -> dict | None:
        return self.latest_asset(asset_type="runtime_bridge_state", actor_role="system")

    def get_runtime_bridge_state_asset(self, *, max_age_seconds: int | None = None) -> dict | None:
        asset = self.latest_runtime_bridge_state_asset()
        if asset is None or max_age_seconds is None:
            return asset
        payload = dict(asset.get("payload") or {})
        raw_timestamp = payload.get("refreshed_at_utc") or asset.get("created_at")
        try:
            refreshed_at = datetime.fromisoformat(str(raw_timestamp).replace("Z", "+00:00"))
        except Exception:
            return None
        if refreshed_at.tzinfo is None:
            refreshed_at = refreshed_at.replace(tzinfo=UTC)
        if (datetime.now(UTC) - refreshed_at.astimezone(UTC)).total_seconds() > max_age_seconds:
            return None
        return asset

    def recent_assets(
        self,
        *,
        asset_type: str | None = None,
        actor_role: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        return self.repository.recent_assets(asset_type=asset_type, actor_role=actor_role, limit=limit)

    def latest_rt_tactical_map(
        self,
        *,
        strategy_key: str | None = None,
        lock_mode: str | None = None,
        require_coins: bool = False,
        limit: int = 20,
    ) -> dict | None:
        normalized_lock_mode = str(lock_mode or "").strip() or None
        for asset in self.recent_assets(asset_type="rt_tactical_map", actor_role="risk_trader", limit=limit):
            payload = dict(asset.get("payload") or {})
            if strategy_key is not None and str(payload.get("strategy_key") or "") != strategy_key:
                continue
            asset_lock_mode = str(payload.get("lock_mode") or "").strip() or None
            if asset_lock_mode != normalized_lock_mode:
                continue
            if require_coins and not self._rt_tactical_map_has_coins(asset):
                continue
            return asset
        return None

    def materialize_rt_tactical_map(
        self,
        *,
        trace_id: str,
        strategy_key: str,
        lock_mode: str | None,
        authored_payload: dict,
        actor_role: str = "risk_trader",
        source_ref: str | None = None,
        group_key: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        now = datetime.now(UTC)
        canonical_payload = dict(authored_payload)
        refresh_reason = str(
            canonical_payload.pop("refresh_reason", None)
            or canonical_payload.pop("map_refresh_reason", None)
            or "rt_tactical_refresh"
        ).strip() or "rt_tactical_refresh"
        canonical_payload.update(
            {
                "map_id": new_id("rt_tactical_map"),
                "strategy_key": strategy_key,
                "updated_at_utc": now.isoformat(),
                "refresh_reason": refresh_reason,
                "lock_mode": str(lock_mode or "").strip() or None,
            }
        )
        canonical_payload = RTTacticalMapAsset.model_validate(canonical_payload).model_dump(mode="json")
        self.save_asset(
            asset_type="rt_tactical_map",
            asset_id=str(canonical_payload["map_id"]),
            payload=canonical_payload,
            trace_id=trace_id,
            actor_role=actor_role,
            group_key=group_key or strategy_key,
            source_ref=source_ref,
            metadata=metadata or {},
        )
        return canonical_payload

    def materialize_runtime_bridge_state(
        self,
        *,
        trace_id: str,
        authored_payload: dict,
        actor_role: str = "system",
        group_key: str = "global",
        source_ref: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        canonical_payload = RuntimeBridgeState.model_validate(authored_payload).model_dump(mode="json")
        return self.save_asset(
            asset_type="runtime_bridge_state",
            payload=canonical_payload,
            trace_id=trace_id,
            actor_role=actor_role,
            group_key=group_key,
            source_ref=source_ref,
            metadata=metadata,
        )

    def materialize_retro_case(
        self,
        *,
        trace_id: str,
        authored_payload: dict,
        actor_role: str = "system",
        source_ref: str | None = None,
        group_key: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        now = datetime.now(UTC)
        canonical_payload = dict(authored_payload)
        # A retro_case is always the case for a specific trading day. If the
        # caller omitted case_day_utc, inherit it from the linked cycle's
        # trade_day_utc rather than defaulting to "now" — otherwise a case
        # created just after UTC rollover for yesterday's cycle would claim
        # today's date and silently disagree with its own cycle.
        resolved_case_day = canonical_payload.get("case_day_utc")
        if not resolved_case_day:
            linked_cycle_id = canonical_payload.get("cycle_id")
            if linked_cycle_id:
                linked_cycle = self.get_retro_cycle_state(cycle_id=str(linked_cycle_id))
                if linked_cycle and linked_cycle.get("trade_day_utc"):
                    resolved_case_day = str(linked_cycle["trade_day_utc"])
        canonical_payload.update(
            {
                "case_id": str(canonical_payload.get("case_id") or new_id("retro_case")),
                "cycle_id": str(canonical_payload.get("cycle_id") or new_id("retro_cycle")),
                "case_day_utc": str(resolved_case_day or now.date().isoformat()),
                "created_at_utc": canonical_payload.get("created_at_utc") or now.isoformat(),
            }
        )
        canonical_payload = RetroCaseAsset.model_validate(canonical_payload).model_dump(mode="json")
        self.save_asset(
            asset_type="retro_case",
            asset_id=str(canonical_payload["case_id"]),
            payload=canonical_payload,
            trace_id=trace_id,
            actor_role=actor_role,
            group_key=group_key or str(canonical_payload["case_day_utc"]),
            source_ref=source_ref,
            metadata=metadata or {},
        )
        return canonical_payload

    def get_retro_case(self, *, case_id: str) -> dict | None:
        asset = self.get_asset(case_id)
        if asset is None or str(asset.get("asset_type") or "") != "retro_case":
            return None
        payload = dict(asset.get("payload") or {})
        return {
            "asset_id": asset.get("asset_id"),
            **payload,
        }

    def latest_retro_case(self, *, case_day_utc: str | None = None) -> dict | None:
        assets = self.recent_assets(asset_type="retro_case", actor_role="system", limit=10)
        for asset in assets:
            payload = dict(asset.get("payload") or {})
            if case_day_utc is not None and str(payload.get("case_day_utc") or "") != case_day_utc:
                continue
            return {
                "asset_id": asset.get("asset_id"),
                **payload,
            }
        return None

    def materialize_retro_brief(
        self,
        *,
        trace_id: str,
        case_id: str,
        agent_role: str,
        authored_payload: dict,
        cycle_id: str | None = None,
        source_ref: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        now = datetime.now(UTC)
        resolved_cycle_id = str(cycle_id or "").strip()
        if not resolved_cycle_id and case_id:
            resolved_cycle_id = str((self.get_retro_case(case_id=case_id) or {}).get("cycle_id") or "").strip()
        canonical_payload = dict(authored_payload)
        canonical_payload.update(
            {
                "brief_id": str(canonical_payload.get("brief_id") or new_id("retro_brief")),
                "cycle_id": str(canonical_payload.get("cycle_id") or resolved_cycle_id or new_id("retro_cycle")),
                "case_id": case_id,
                "agent_role": agent_role,
                "created_at_utc": canonical_payload.get("created_at_utc") or now.isoformat(),
            }
        )
        canonical_payload = RetroBriefAsset.model_validate(canonical_payload).model_dump(mode="json")
        self.save_asset(
            asset_type="retro_brief",
            asset_id=str(canonical_payload["brief_id"]),
            payload=canonical_payload,
            trace_id=trace_id,
            actor_role=agent_role,
            group_key=case_id,
            source_ref=source_ref,
            metadata=metadata or {},
        )
        return canonical_payload

    def get_retro_briefs(
        self,
        *,
        case_id: str | None = None,
        cycle_id: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        briefs: list[dict] = []
        for asset in self.recent_assets(asset_type="retro_brief", limit=limit):
            payload = dict(asset.get("payload") or {})
            if case_id is not None and str(payload.get("case_id") or "") != case_id:
                continue
            if cycle_id is not None and str(payload.get("cycle_id") or "") != cycle_id:
                continue
            briefs.append(
                {
                    "asset_id": asset.get("asset_id"),
                    **payload,
                }
            )
        return briefs

    def latest_retro_brief(self, *, case_id: str | None = None, cycle_id: str | None = None, agent_role: str) -> dict | None:
        for asset in self.recent_assets(asset_type="retro_brief", actor_role=agent_role, limit=10):
            payload = dict(asset.get("payload") or {})
            if case_id is not None and str(payload.get("case_id") or "") != case_id:
                continue
            if cycle_id is not None and str(payload.get("cycle_id") or "") != cycle_id:
                continue
            return {
                "asset_id": asset.get("asset_id"),
                **payload,
            }
        return None

    def materialize_retro_cycle_state(
        self,
        *,
        trace_id: str,
        authored_payload: dict,
        actor_role: str = "system",
        source_ref: str | None = None,
        group_key: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        now = datetime.now(UTC)
        canonical_payload = dict(authored_payload)
        canonical_payload.update(
            {
                "cycle_id": str(canonical_payload.get("cycle_id") or new_id("retro_cycle")),
                "trade_day_utc": str(canonical_payload.get("trade_day_utc") or now.date().isoformat()),
                "started_at_utc": canonical_payload.get("started_at_utc") or now.isoformat(),
            }
        )
        canonical_payload = RetroCycleStateAsset.model_validate(canonical_payload).model_dump(mode="json")
        self.save_asset(
            asset_type="retro_cycle_state",
            asset_id=str(canonical_payload["cycle_id"]),
            payload=canonical_payload,
            trace_id=trace_id,
            actor_role=actor_role,
            group_key=group_key or str(canonical_payload["trade_day_utc"]),
            source_ref=source_ref,
            metadata=metadata or {},
        )
        return canonical_payload

    def save_retro_cycle_state(
        self,
        *,
        trace_id: str | None,
        cycle_id: str,
        payload: dict,
        actor_role: str = "system",
        source_ref: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        canonical_payload = dict(payload)
        canonical_payload["cycle_id"] = cycle_id
        canonical_payload = RetroCycleStateAsset.model_validate(canonical_payload).model_dump(mode="json")
        self.save_asset(
            asset_type="retro_cycle_state",
            asset_id=cycle_id,
            payload=canonical_payload,
            trace_id=trace_id,
            actor_role=actor_role,
            group_key=str(canonical_payload["trade_day_utc"]),
            source_ref=source_ref,
            metadata=metadata or {},
        )
        return canonical_payload

    def get_retro_cycle_state(self, *, cycle_id: str) -> dict | None:
        asset = self.get_asset(cycle_id)
        if asset is None or str(asset.get("asset_type") or "") != "retro_cycle_state":
            return None
        payload = dict(asset.get("payload") or {})
        return {
            "asset_id": asset.get("asset_id"),
            **payload,
        }

    def latest_retro_cycle_state(self, *, trade_day_utc: str | None = None) -> dict | None:
        assets = self.recent_assets(asset_type="retro_cycle_state", actor_role="system", limit=10)
        for asset in assets:
            payload = dict(asset.get("payload") or {})
            if trade_day_utc is not None and str(payload.get("trade_day_utc") or "") != trade_day_utc:
                continue
            return {
                "asset_id": asset.get("asset_id"),
                **payload,
            }
        return None

    def materialize_learning_directive(
        self,
        *,
        trace_id: str,
        case_id: str,
        agent_role: str,
        session_key: str,
        learning_path: str,
        authored_payload: dict,
        cycle_id: str | None = None,
        actor_role: str = "crypto_chief",
        source_ref: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        now = datetime.now(UTC)
        resolved_cycle_id = str(cycle_id or "").strip()
        if not resolved_cycle_id and case_id:
            resolved_cycle_id = str((self.get_retro_case(case_id=case_id) or {}).get("cycle_id") or "").strip()
        canonical_payload = dict(authored_payload)
        canonical_payload.update(
            {
                "directive_id": str(canonical_payload.get("directive_id") or new_id("learning_directive")),
                "cycle_id": str(canonical_payload.get("cycle_id") or resolved_cycle_id or new_id("retro_cycle")),
                "case_id": case_id,
                "agent_role": agent_role,
                "created_at_utc": canonical_payload.get("created_at_utc") or now.isoformat(),
                "issued_at_utc": canonical_payload.get("issued_at_utc") or now.isoformat(),
                "session_key": session_key,
                "learning_path": learning_path,
            }
        )
        canonical_payload = LearningDirectiveAsset.model_validate(canonical_payload).model_dump(mode="json")
        self.save_asset(
            asset_type="learning_directive",
            asset_id=str(canonical_payload["directive_id"]),
            payload=canonical_payload,
            trace_id=trace_id,
            actor_role=actor_role,
            group_key=case_id,
            source_ref=source_ref,
            metadata=metadata or {},
        )
        return canonical_payload

    def save_learning_directive(
        self,
        *,
        trace_id: str | None,
        directive_id: str,
        payload: dict,
        actor_role: str = "system",
        source_ref: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        canonical_payload = dict(payload)
        canonical_payload["directive_id"] = directive_id
        canonical_payload = LearningDirectiveAsset.model_validate(canonical_payload).model_dump(mode="json")
        self.save_asset(
            asset_type="learning_directive",
            asset_id=directive_id,
            payload=canonical_payload,
            trace_id=trace_id,
            actor_role=actor_role,
            group_key=str(canonical_payload["case_id"]),
            source_ref=source_ref,
            metadata=metadata or {},
        )
        return canonical_payload

    def get_learning_directives(
        self,
        *,
        case_id: str | None = None,
        cycle_id: str | None = None,
        agent_role: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        directives: list[dict] = []
        for asset in self.recent_assets(asset_type="learning_directive", limit=limit):
            payload = dict(asset.get("payload") or {})
            if case_id is not None and str(payload.get("case_id") or "") != case_id:
                continue
            if cycle_id is not None and str(payload.get("cycle_id") or "") != cycle_id:
                continue
            if agent_role is not None and str(payload.get("agent_role") or "") != agent_role:
                continue
            directives.append(
                {
                    "asset_id": asset.get("asset_id"),
                    **payload,
                }
            )
        return directives

    def latest_learning_directive(self, *, agent_role: str, cycle_id: str | None = None) -> dict | None:
        for asset in self.recent_assets(asset_type="learning_directive", limit=20):
            payload = dict(asset.get("payload") or {})
            if str(payload.get("agent_role") or "") != agent_role:
                continue
            if cycle_id is not None and str(payload.get("cycle_id") or "") != cycle_id:
                continue
            return {
                "asset_id": asset.get("asset_id"),
                **payload,
            }
        return None

    def get_pending_scheduled_rechecks(self) -> list[dict]:
        latest_strategy = self.get_latest_strategy()
        if latest_strategy is None:
            return []
        payload = latest_strategy.get("payload") or {}
        rechecks = list(payload.get("scheduled_rechecks") or [])
        now = datetime.now(UTC)
        pending: list[dict] = []
        for item in rechecks:
            if not isinstance(item, dict):
                continue
            raw = item.get("recheck_at_utc")
            try:
                recheck_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except Exception:
                recheck_at = None
            if recheck_at is None or recheck_at >= now:
                pending.append(dict(item))
        return pending

    def get_due_scheduled_rechecks(self, *, now: datetime | None = None) -> list[dict]:
        latest_strategy = self.get_latest_strategy()
        if latest_strategy is None:
            return []
        payload = latest_strategy.get("payload") or {}
        strategy_id = str(payload.get("strategy_id") or "").strip() or None
        revision_number = payload.get("revision_number")
        current = now or datetime.now(UTC)
        due: list[dict] = []
        for item in list(payload.get("scheduled_rechecks") or []):
            if not isinstance(item, dict):
                continue
            raw = item.get("recheck_at_utc")
            try:
                recheck_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except Exception:
                continue
            if recheck_at.tzinfo is None:
                recheck_at = recheck_at.replace(tzinfo=UTC)
            if recheck_at.astimezone(UTC) > current.astimezone(UTC):
                continue
            enriched = dict(item)
            if strategy_id:
                enriched["strategy_id"] = strategy_id
            if revision_number is not None:
                enriched["revision_number"] = revision_number
            due.append(enriched)
        return due

    @staticmethod
    def _rt_tactical_map_has_coins(asset: dict | None) -> bool:
        payload = dict((asset or {}).get("payload") or {})
        coins = payload.get("coins") or []
        return isinstance(coins, list) and any(isinstance(item, dict) and item.get("coin") for item in coins)

    def claim_pending_pm_trigger_event(
        self,
        *,
        claim_ref: str,
        max_age_minutes: int = 30,
    ) -> dict | None:
        current = datetime.now(UTC)
        candidates: list[tuple[datetime, dict]] = []
        for asset in self.recent_assets(asset_type="pm_trigger_event", actor_role="system", limit=20):
            payload = dict(asset.get("payload") or {})
            if payload.get("claimed_at_utc"):
                continue
            if not bool(payload.get("claimable", payload.get("dispatched"))):
                continue
            detected_at = _parse_utc_datetime(payload.get("detected_at_utc") or asset.get("created_at"))
            if detected_at is None:
                continue
            if current - detected_at > timedelta(minutes=max_age_minutes):
                continue
            candidates.append((detected_at, asset))

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[0])
        _, asset = candidates[0]
        payload = dict(asset.get("payload") or {})
        payload["claimed_at_utc"] = current.isoformat()
        payload["claimed_ref"] = claim_ref
        metadata = dict(asset.get("metadata") or {})
        metadata["claim_status"] = "claimed"
        metadata["claimed_ref"] = claim_ref
        self.save_asset(
            asset_type="pm_trigger_event",
            asset_id=str(asset.get("asset_id") or ""),
            payload=payload,
            trace_id=asset.get("trace_id"),
            actor_role=asset.get("actor_role"),
            group_key=asset.get("group_key"),
            source_ref=asset.get("source_ref"),
            metadata=metadata,
        )
        return {
            "created_at": asset.get("created_at"),
            "asset_id": asset.get("asset_id"),
            **payload,
        }

    def find_recent_pm_trigger_event(
        self,
        *,
        trigger_category: str | None = None,
        max_age_minutes: int = 10,
    ) -> dict | None:
        current = datetime.now(UTC)
        normalized_category = str(trigger_category or "").strip() or None
        for asset in self.recent_assets(asset_type="pm_trigger_event", actor_role="system", limit=20):
            payload = dict(asset.get("payload") or {})
            if normalized_category is not None:
                category = str(payload.get("trigger_category") or "").strip()
                if category != normalized_category:
                    continue
            detected_at = _parse_utc_datetime(payload.get("detected_at_utc") or asset.get("created_at"))
            if detected_at is None:
                continue
            if current - detected_at > timedelta(minutes=max_age_minutes):
                continue
            return {
                "created_at": asset.get("created_at"),
                "asset_id": asset.get("asset_id"),
                **payload,
            }
        return None

    def get_macro_memory(self, *, limit: int = 5) -> list[dict]:
        macro_daily = self.recent_assets(asset_type="macro_daily_memory", limit=limit)
        if macro_daily:
            return [item["payload"] for item in macro_daily]
        return [item["payload"] for item in self.recent_assets(asset_type="macro_event", limit=max(limit, 10))]

    def get_recent_execution_results(self, *, limit: int = 10) -> list[dict]:
        return [item["payload"] for item in self.recent_assets(asset_type="execution_result", limit=limit)]

    def get_recent_execution_thoughts(self, *, limit: int = 5) -> list[dict]:
        batch_assets = self.recent_assets(asset_type="execution_batch", actor_role="risk_trader", limit=max(limit * 3, 10))
        result_assets = self.recent_assets(asset_type="execution_result", actor_role="risk_trader", limit=max(limit * 6, 20))

        results_by_key: dict[tuple[str, str], dict] = {}
        for asset in result_assets:
            payload = dict(asset.get("payload") or {})
            decision_id = str(payload.get("decision_id") or "").strip()
            coin = str(payload.get("coin") or "").strip().upper()
            if not decision_id or not coin:
                continue
            results_by_key.setdefault((decision_id, coin), payload)

        thoughts: list[dict] = []
        for asset in batch_assets:
            payload = dict(asset.get("payload") or {})
            decision_id = str(payload.get("decision_id") or "").strip()
            if not decision_id:
                continue
            strategy_id = str(payload.get("strategy_id") or "").strip() or None
            generated_at_utc = payload.get("generated_at_utc") or asset.get("created_at")
            for item in list(payload.get("decisions") or []):
                if not isinstance(item, dict):
                    continue
                symbol = str(item.get("symbol") or "").strip().upper()
                if not symbol:
                    continue
                thoughts.append(
                    {
                        "generated_at_utc": generated_at_utc,
                        "decision_id": decision_id,
                        "strategy_id": strategy_id,
                        "symbol": symbol,
                        "action": item.get("action"),
                        "direction": item.get("direction"),
                        "reason": item.get("reason"),
                        "reference_take_profit_condition": item.get("reference_take_profit_condition"),
                        "reference_stop_loss_condition": item.get("reference_stop_loss_condition"),
                        "size_pct_of_exposure_budget": item.get("size_pct_of_exposure_budget", item.get("size_pct_of_equity")),
                        "urgency": item.get("urgency"),
                        "execution_result": self._compact_execution_result_for_thought(
                            results_by_key.get((decision_id, symbol))
                        ),
                    }
                )
                if len(thoughts) >= limit:
                    return thoughts
        return thoughts

    def get_recent_news_submissions(self, *, limit: int = 10) -> list[dict]:
        return [item["payload"] for item in self.recent_assets(asset_type="news_submission", limit=limit)]

    def save_agent_session(
        self,
        *,
        agent_role: str,
        session_id: str,
        status: str = "active",
        last_task_kind: str | None = None,
        last_submission_kind: str | None = None,
        last_reset_command: str | None = None,
    ) -> AgentSessionState:
        state = AgentSessionState(
            agent_role=agent_role,
            session_id=session_id,
            status=status,
            last_task_kind=last_task_kind,
            last_submission_kind=last_submission_kind,
            last_reset_command=last_reset_command,
        )
        self.repository.save_agent_session(state)
        return state

    def get_agent_session(self, agent_role: str) -> AgentSessionState | None:
        return self.repository.get_agent_session(agent_role)

    def list_agent_sessions(self) -> list[dict]:
        return self.repository.list_agent_sessions()

    def save_notification_result(self, result: NotificationResult, payload: dict) -> EventEnvelope:
        self.repository.save_notification_result(result, payload)
        self.save_asset(
            asset_type="notification_result",
            payload={
                "notification_id": result.notification_id,
                "delivered": result.delivered,
                "provider_message_id": result.provider_message_id,
                "failure_reason": result.failure_reason,
                "delivered_at": result.delivered_at.isoformat(),
                "command": payload,
            },
            trace_id=payload.get("trace_id"),
            actor_role="system",
            group_key=result.notification_id,
        )
        event = EventFactory.build(
            trace_id=payload.get("trace_id", "notification"),
            event_type=EVENT_NOTIFICATION_RECORDED,
            source_module=MODULE_NAME,
            entity_type="notification_result",
            entity_id=result.notification_id,
            payload={"result": result.model_dump(mode="json"), "command": payload},
        )
        self.append_event(event)
        return event

    def list_parameters(self) -> list[dict]:
        return self.repository.list_parameters()

    def save_parameter(self, name: str, scope: str, value: dict, *, operator: str, reason: str) -> EventEnvelope:
        self.repository.save_parameter(name, scope, value, operator=operator, reason=reason)
        event = EventFactory.build(
            trace_id="parameters",
            event_type=EVENT_PARAMETER_CHANGED,
            source_module=MODULE_NAME,
            entity_type="parameter",
            entity_id=f"{scope}:{name}",
            payload={
                "name": name,
                "scope": scope,
                "value": value,
                "operator": operator,
                "reason": reason,
            },
        )
        self.append_event(event)
        return event

    def capture_snapshot(self, trace_id: str) -> tuple[StateSnapshot, EventEnvelope]:
        snapshot = self.repository.capture_snapshot(trace_id)
        event = EventFactory.build(
            trace_id=trace_id,
            event_type=EVENT_STATE_SNAPSHOT_CAPTURED,
            source_module=MODULE_NAME,
            entity_type="state_snapshot",
            entity_id=snapshot.snapshot_id,
            payload=snapshot.model_dump(mode="json"),
        )
        self.append_event(event)
        return snapshot, event

    def query_replay(self, *, trace_id: str | None = None, module: str | None = None) -> ReplayQueryView:
        return self.repository.query_replay(trace_id=trace_id, module=module)

    def ensure_bootstrap_parameter(self, name: str, scope: str, value: dict, *, operator: str, reason: str) -> None:
        existing = {f"{row['scope']}:{row['name']}" for row in self.list_parameters()}
        if f"{scope}:{name}" not in existing:
            self.save_parameter(name, scope, value, operator=operator, reason=reason)

    def build_overview(self) -> OverviewQueryView:
        latest_strategy = self.latest_asset(asset_type="strategy")
        latest_portfolio = self.latest_asset(asset_type="portfolio_snapshot") or self.latest_portfolio()
        risk_overlay = self._build_portfolio_risk_overlay()
        latest_execution_batch = self.latest_asset(asset_type="execution_batch")
        recent_execution_results = self.recent_assets(asset_type="execution_result", limit=10)
        current_macro_events = self.recent_assets(asset_type="macro_event", limit=10)
        recent_notifications = self.recent_assets(asset_type="notification_result", limit=10)
        recent_events = self.query_events(limit=25)
        freshness_candidates = [
            latest_strategy["created_at"] if latest_strategy else None,
            latest_portfolio["created_at"] if latest_portfolio else None,
            latest_execution_batch["created_at"] if latest_execution_batch else None,
            recent_execution_results[0]["created_at"] if recent_execution_results else None,
            current_macro_events[0]["created_at"] if current_macro_events else None,
            recent_notifications[0]["created_at"] if recent_notifications else None,
            recent_events[0]["occurred_at"] if recent_events else None,
        ]
        latest_data_at = max((value for value in freshness_candidates if value), default=None)
        data_age_seconds: float | None = None
        if latest_data_at:
            try:
                data_age_seconds = max(
                    0.0,
                    (datetime.now(UTC) - datetime.fromisoformat(latest_data_at)).total_seconds(),
                )
            except ValueError:
                data_age_seconds = None
        is_stale = bool(data_age_seconds is not None and data_age_seconds > 30 * 60)
        # Pull ~31 days of equity history, downsampled to 15-minute buckets so the
        # daily chart can actually see multi-day trends without hauling millions of
        # raw snapshots across the wire.
        history_since = (datetime.now(UTC) - timedelta(days=31)).isoformat()
        portfolio_history = [
            {
                "created_at": item["created_at"],
                "total_equity_usd": item.get("total_equity_usd"),
            }
            for item in self.portfolio_equity_timeseries(since=history_since, bucket_minutes=15)
        ]
        return OverviewQueryView(
            system={
                "strategy_present": latest_strategy is not None,
                "execution_present": latest_execution_batch is not None,
                "macro_event_count": len(current_macro_events),
                "updated_at": latest_data_at,
                "built_at": datetime.now(UTC).isoformat(),
                "data_age_seconds": data_age_seconds,
                "is_stale": is_stale,
            },
            latest_strategy=latest_strategy,
            latest_portfolio=latest_portfolio,
            risk_overlay=risk_overlay,
            portfolio_history=portfolio_history,
            latest_execution_batch=latest_execution_batch,
            recent_execution_results=recent_execution_results,
            current_macro_events=current_macro_events,
            agent_sessions=self.list_agent_sessions(),
            recent_notifications=recent_notifications,
            recent_events=recent_events,
        )

    _RISK_STATE_RANK = {"normal": 0, "observe": 1, "reduce": 2, "exit": 3, "breaker": 4}

    def _build_portfolio_risk_overlay(self) -> dict[str, object] | None:
        latest_policy = self.latest_asset(asset_type="policy_guard")
        if latest_policy is None:
            return None
        payload = latest_policy.get("payload") or {}
        if not isinstance(payload, dict):
            return None
        portfolio_state = payload.get("portfolio_risk_state") or {}
        if not isinstance(portfolio_state, dict):
            return None
        thresholds = portfolio_state.get("thresholds") or {}
        if not isinstance(thresholds, dict):
            thresholds = {}

        day_peak_equity = self._parse_float(portfolio_state.get("day_peak_equity_usd"))
        if day_peak_equity is None or day_peak_equity <= 0:
            return None

        # `policy_guard` assets carry the INSTANTANEOUS state from each evaluation.
        # Clamp upward to the day's worst-so-far (ladder_high) from `risk_brake_state`
        # so the frontend shows a sticky safety-ladder: once crossed, a threshold
        # stays "triggered" until UTC rollover even if equity recovers.
        instantaneous_state = str(portfolio_state.get("state") or "normal")
        ladder_high = self._load_ladder_high_state()
        effective_state = self._max_rank_state(instantaneous_state, ladder_high)

        overlay: dict[str, object] = {
            "state": effective_state,
            "day_peak_equity_usd": str(portfolio_state.get("day_peak_equity_usd") or ""),
            "current_equity_usd": str(portfolio_state.get("current_equity_usd") or ""),
        }
        if ladder_high and ladder_high != "normal":
            overlay["ladder_high_state"] = ladder_high
        if instantaneous_state != effective_state:
            overlay["instantaneous_state"] = instantaneous_state
        for key in ("observe", "reduce", "exit"):
            drawdown_key = f"{key}_drawdown_pct"
            drawdown_pct = self._parse_float(thresholds.get(drawdown_key))
            if drawdown_pct is None:
                continue
            overlay[key] = {
                "drawdown_pct": round(drawdown_pct, 4),
                "equity_usd": str(round(day_peak_equity * (1.0 - drawdown_pct / 100.0), 8)),
            }
        return overlay

    def _load_ladder_high_state(self) -> str:
        asset = self.get_asset("risk_brake_state")
        if asset is None:
            return "normal"
        payload = asset.get("payload")
        if not isinstance(payload, dict):
            return "normal"
        value = str(payload.get("portfolio_state_ladder_high") or "normal").lower()
        return value if value in self._RISK_STATE_RANK else "normal"

    @classmethod
    def _max_rank_state(cls, left: str, right: str) -> str:
        left_rank = cls._RISK_STATE_RANK.get(left, 0)
        right_rank = cls._RISK_STATE_RANK.get(right, 0)
        return left if left_rank >= right_rank else right

    @staticmethod
    def _parse_float(value: object) -> float | None:
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return number if number == number else None

    @staticmethod
    def _compact_execution_result_for_thought(payload: dict | None) -> dict | None:
        if not payload:
            return None
        fills = list(payload.get("fills") or [])
        first_fill = dict(fills[0]) if fills else {}
        return {
            "success": payload.get("success"),
            "technical_failure": payload.get("technical_failure"),
            "message": payload.get("message"),
            "exchange_order_id": payload.get("exchange_order_id"),
            "notional_usd": payload.get("notional_usd"),
            "executed_at": payload.get("executed_at"),
            "fills_count": len(fills),
            "first_fill_price": first_fill.get("price"),
            "first_fill_size": first_fill.get("size"),
        }


def _parse_utc_datetime(raw: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
