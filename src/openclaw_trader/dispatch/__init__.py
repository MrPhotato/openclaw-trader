from __future__ import annotations

import json
import subprocess
import sys
import time
import traceback
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo
from zlib import crc32

from ..coinbase import CoinbaseAdvancedClient
from ..briefs import write_dispatch_brief, write_perp_dispatch_brief, write_perp_news_brief
from ..config import RuntimeConfig, load_coinbase_credentials, load_runtime_config
from ..engine import EngineContext, TraderEngine
from ..models import AutopilotDecision, AutopilotPhase
from ..news.monitor import sync_news
from ..perps import build_perp_engine
from ..perps.runtime import PerpSupervisor
from ..state import StateStore
from ..strategy import (
    STRATEGY_DAY_MD,
    append_position_journal_entry,
    build_strategy_input,
    build_strategy_input_perps,
    clear_strategy_pending_regime_shift,
    current_strategy_schedule_slot,
    load_current_strategy,
    mark_strategy_regime_shift_rewrite,
    parse_strategy_response,
    routine_refresh_due,
    save_strategy_doc,
    scheduled_recheck_reason,
    strategy_update_is_material,
    strategy_rewrite_reason,
)
from ..models import EntryWorkflowMode, LlmTradeReviewDecision, LlmTradeReviewOrderDecision

from .parsing import (
    DispatchAction,
    _extract_first_payload_text,
    _optional_decimal,
    parse_trade_review_response,
)
from .execution import build_position_journal_entry, execute_trade_batch, serialize_position_snapshot
from .notifications import (
    deliver_generated_message,
    format_daily_report_message,
    format_trade_event_message,
    notify_strategy_update,
    resolve_owner_main_agent,
    should_emit_trade_event,
)
from .planning import build_dispatch_actions
from .prompts import (
    DAILY_REPORT_PROMPT,
    DAILY_STRATEGY_SLOT_LOCK_PREFIX,
    EVENT_PROMPT,
    FALLBACK_PROMPT,
    STRATEGY_NOTIFY_PROMPT,
    STRATEGY_PROMPT,
    TRADE_REVIEW_PROMPT,
    WECOM_NAMESPACE_REGISTRY,
)
from .state_flow import (
    acquire_daily_strategy_slot_lock,
    daily_report_due,
    daily_strategy_slot_lock_key,
    fallback_due,
    last_llm_trigger_at,
    mark_daily_report,
    mark_llm_trigger,
    mark_scheduled_recheck,
    mark_strategy,
    release_daily_strategy_slot_lock,
)
from .strategy_flow import (
    allowed_strategy_symbols,
    apply_strategy_action,
    refresh_strategy_context_reports,
    run_strategy_refresh_flow,
)
from .trade_review import approved_trade_plans, scale_trade_plan, trade_review_candidates

class OpenClawAgentRunner:
    def __init__(self, runtime: RuntimeConfig):
        self.runtime = runtime

    def _session_target_for_action(self, action: DispatchAction, now: datetime) -> str:
        tz = ZoneInfo(self.runtime.dispatch.daily_report_timezone)
        local_now = now.astimezone(tz)
        year_digit = local_now.year % 10
        day_of_year = int(local_now.strftime("%j"))
        kind_code = {
            "strategy": 11,
            "trade_review": 12,
            "event": 13,
            "fallback": 14,
            "daily_report": 15,
        }.get(action.kind, 99)
        bucket = crc32(f"{action.kind}|{action.reason}".encode("utf-8")) % 10000
        # Keep an E.164-like target while rotating by day and reason to avoid indefinite context bleed.
        return f"+1999{year_digit}{day_of_year:03d}{kind_code:02d}{bucket:04d}"

    def run(self, action: DispatchAction, *, now: datetime | None = None) -> dict:
        dispatch = self.runtime.dispatch
        reference_now = now or datetime.now(UTC)
        agent_id = getattr(action, "agent_id", "crypto-chief")
        cmd = [
            "openclaw",
            "agent",
            "--agent",
            agent_id,
            "--to",
            self._session_target_for_action(action, reference_now),
            "--message",
            action.message,
            "--thinking",
            dispatch.thinking,
            "--timeout",
            str(dispatch.timeout_seconds),
            "--json",
        ]
        if action.deliver:
            cmd.extend(
                [
                    "--deliver",
                    "--reply-channel",
                    dispatch.reply_channel,
                    "--reply-to",
                    dispatch.reply_to,
                    "--reply-account",
                    dispatch.reply_account_id,
                ]
            )
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=dispatch.timeout_seconds + dispatch.process_timeout_grace_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "success": False,
                "returncode": None,
                "stdout": (exc.stdout or "").strip() if isinstance(exc.stdout, str) else "",
                "stderr": (exc.stderr or "").strip() if isinstance(exc.stderr, str) else "",
                "payload": {},
                "timeout": True,
                "message": f"openclaw agent timed out after {dispatch.timeout_seconds + dispatch.process_timeout_grace_seconds}s",
            }
        payload: dict[str, object]
        if proc.stdout.strip():
            try:
                payload = json.loads(proc.stdout)
            except json.JSONDecodeError:
                payload = {"stdout": proc.stdout.strip()}
        else:
            payload = {}
        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "payload": payload,
        }

    def send_text(self, message: str) -> dict[str, object]:
        dispatch = self.runtime.dispatch
        cmd = [
            "openclaw",
            "message",
            "send",
            "--target",
            dispatch.reply_to,
            "--message",
            message,
            "--json",
        ]
        if dispatch.reply_account_id:
            cmd.extend(["--account", dispatch.reply_account_id])
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=dispatch.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "success": False,
                "returncode": None,
                "stdout": (exc.stdout or "").strip() if isinstance(exc.stdout, str) else "",
                "stderr": (exc.stderr or "").strip() if isinstance(exc.stderr, str) else "",
                "timeout": True,
                "message": f"openclaw message send timed out after {dispatch.timeout_seconds}s",
            }
        payload: dict[str, object]
        if proc.stdout.strip():
            try:
                payload = json.loads(proc.stdout)
            except json.JSONDecodeError:
                payload = {"stdout": proc.stdout.strip()}
        else:
            payload = {}
        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "payload": payload,
            "text": message,
        }


def _resolve_owner_main_agent(reply_to: str) -> str:
    return resolve_owner_main_agent(reply_to, registry_path=WECOM_NAMESPACE_REGISTRY)


def _notify_strategy_update(
    runner: OpenClawAgentRunner,
    runtime: RuntimeConfig,
    *,
    now: datetime,
    reason: str,
    strategy_doc: dict[str, Any] | None = None,
) -> dict[str, object]:
    return notify_strategy_update(
        runner,
        runtime,
        now=now,
        reason=reason,
        resolve_owner_main_agent_fn=_resolve_owner_main_agent,
        strategy_doc=strategy_doc,
    )


def _allowed_strategy_symbols(runtime: RuntimeConfig) -> set[str]:
    return allowed_strategy_symbols(runtime)


class TriggerDispatcher:
    def __init__(
        self,
        runtime: RuntimeConfig,
        state: StateStore,
        runner: OpenClawAgentRunner,
    ):
        self.runtime = runtime
        self.state = state
        self.runner = runner

    def _last_llm_trigger_at(self) -> datetime | None:
        return last_llm_trigger_at(self.state)

    def _mark_llm_trigger(self, now: datetime) -> None:
        mark_llm_trigger(self.state, now)

    def _daily_report_due(self, now: datetime) -> bool:
        return daily_report_due(self.state, self.runtime, now)

    def _mark_daily_report(self, now: datetime) -> None:
        mark_daily_report(self.state, self.runtime, now)

    def _fallback_due(self, now: datetime) -> bool:
        return fallback_due(self.state, self.runtime, now)

    def _mark_strategy(self, now: datetime, fingerprint: str | None = None, reason: str | None = None) -> None:
        mark_strategy(
            self.state,
            self.runtime,
            now,
            fingerprint=fingerprint,
            reason=reason,
            current_strategy_schedule_slot_fn=current_strategy_schedule_slot,
            mark_strategy_regime_shift_rewrite_fn=mark_strategy_regime_shift_rewrite,
            clear_strategy_pending_regime_shift_fn=clear_strategy_pending_regime_shift,
        )

    def _mark_scheduled_recheck(self, mark_key: str | None, now: datetime) -> None:
        mark_scheduled_recheck(self.state, mark_key, now)

    def _daily_strategy_slot_lock_key(self, slot_key: str) -> str:
        return daily_strategy_slot_lock_key(slot_key, prefix=DAILY_STRATEGY_SLOT_LOCK_PREFIX)

    def _acquire_daily_strategy_slot_lock(self, slot_key: str, now: datetime) -> bool:
        return acquire_daily_strategy_slot_lock(
            self.state,
            self.runtime,
            slot_key,
            now,
            prefix=DAILY_STRATEGY_SLOT_LOCK_PREFIX,
        )

    def _release_daily_strategy_slot_lock(self, slot_key: str) -> None:
        release_daily_strategy_slot_lock(self.state, slot_key, prefix=DAILY_STRATEGY_SLOT_LOCK_PREFIX)

    def _trade_review_candidates(
        self,
        system_state,
    ) -> list[AutopilotDecision]:
        return trade_review_candidates(system_state)

    def _scale_trade_plan(
        self,
        decision: AutopilotDecision,
        *,
        review_decision: str,
        size_scale: float,
    ) -> dict[str, Any] | None:
        return scale_trade_plan(
            decision,
            review_decision=review_decision,
            size_scale=size_scale,
            optional_decimal=_optional_decimal,
        )

    def _approved_trade_plans(
        self,
        system_state,
        trade_review: LlmTradeReviewDecision,
    ) -> list[dict[str, Any]]:
        return approved_trade_plans(
            system_state,
            trade_review,
            scale_trade_plan_fn=self._scale_trade_plan,
        )

    def _serialize_position_snapshot(self, account: Any) -> dict[str, Any] | None:
        return serialize_position_snapshot(account)

    def _record_position_journal(
        self,
        *,
        now: datetime,
        decision: AutopilotDecision,
        approved_plan: dict[str, Any],
        review: dict[str, Any] | None,
        execution_result: dict[str, Any] | None,
        before_position: dict[str, Any] | None,
        after_position: dict[str, Any] | None,
        success: bool,
    ) -> dict[str, Any]:
        entry = build_position_journal_entry(
            now=now,
            decision=decision,
            approved_plan=approved_plan,
            review=review,
            execution_result=execution_result,
            before_position=before_position,
            after_position=after_position,
            success=success,
            current_strategy=load_current_strategy() or {},
        )
        return append_position_journal_entry(entry)

    def _execute_trade_batch(
        self,
        supervisor,
        approved_trade_plans: list[dict[str, Any]],
        *,
        now: datetime,
    ) -> list[dict[str, Any]]:
        return execute_trade_batch(
            supervisor,
            approved_trade_plans,
            now=now,
            serialize_position_snapshot_fn=self._serialize_position_snapshot,
            record_position_journal_fn=self._record_position_journal,
        )

    def plan_actions(
        self,
        decision: AutopilotDecision,
        now: datetime | None = None,
    ) -> list[DispatchAction]:
        now = now or datetime.now(UTC)
        actions: list[DispatchAction] = []
        strategy_reason = None
        strategy_mark_key = None
        current_strategy = load_current_strategy()
        if current_strategy is None:
            strategy_reason = "strategy_missing"
        else:
            scheduled_recheck = scheduled_recheck_reason(
                self.state,
                current_strategy,
                now=now,
            )
            if scheduled_recheck is not None:
                strategy_reason, strategy_mark_key = scheduled_recheck
            else:
                strategy_reason = strategy_rewrite_reason(
                    self.state,
                    self.runtime.strategy,
                    current_strategy=current_strategy,
                    decision=decision,
                    now=now,
                )
                if strategy_reason is None and routine_refresh_due(self.state, self.runtime.strategy, now):
                    strategy_reason = "routine_refresh"
                    strategy_mark_key = current_strategy_schedule_slot(self.runtime.strategy, now)
        return build_dispatch_actions(
            decision,
            now,
            strategy_reason=strategy_reason,
            strategy_mark_key=strategy_mark_key,
            market_mode=self.runtime.dispatch.market_mode,
            enable_observe_notifications=self.runtime.dispatch.enable_observe_notifications,
            daily_report_due=self._daily_report_due(now),
            fallback_due=self._fallback_due(now),
        )

    def _should_emit_trade_event(
        self,
        decision: AutopilotDecision,
        trade_review: LlmTradeReviewDecision | None,
        approved_trade_plans: list[dict[str, Any]],
        executed_trades: list[dict[str, Any]],
    ) -> bool:
        return should_emit_trade_event(
            decision,
            trade_review,
            approved_trade_plans,
            executed_trades,
            market_mode=self.runtime.dispatch.market_mode,
        )

    def dispatch_once(self, now: datetime | None = None, product_id: str | None = None) -> dict:
        now = now or datetime.now(UTC)
        runtime = load_runtime_config()
        self.runtime = runtime
        self.runner.runtime = runtime
        sync_news(runtime.news, self.state, now=now)
        executed_trades: list[dict[str, object]] = []
        strategy_payload: dict[str, object] | None = None
        trade_review: LlmTradeReviewDecision | None = None
        execution_result: dict[str, Any] | None = None
        approved_trade_plans: list[dict[str, Any]] = []
        skip_trade_review_this_round = False
        transition_context: dict[str, Any] | None = None

        if runtime.dispatch.market_mode == "perps":
            perp_engine = build_perp_engine(runtime, self.state)
            supervisor = PerpSupervisor(runtime=runtime, state=self.state, engine=perp_engine)
            system_state = supervisor.system_state()
            decision = system_state.primary
            actions = self.plan_actions(decision, now)
            if actions:
                write_perp_news_brief(supervisor)
                write_perp_dispatch_brief(supervisor, system_state)
                strategy_payload = build_strategy_input_perps(runtime, supervisor, self.state, now)
            if decision.phase == AutopilotPhase.panic_exit:
                panic_coin = decision.product_id.split("-")[0]
                before_account = supervisor.engine.account(panic_coin)
                before_position = self._serialize_position_snapshot(before_account)
                execution_result = supervisor.apply_trade_plan(decision)
                after_account = supervisor.engine.account(panic_coin)
                after_position = self._serialize_position_snapshot(after_account)
                if execution_result is not None:
                    panic_success = all(step.get("success", False) for step in execution_result.get("results", []))
                    if all(step.get("success", False) for step in execution_result.get("results", [])):
                        supervisor.register_panic_exit(
                            now=now,
                            coin=decision.product_id.split("-")[0],
                            trigger_reason=decision.reason,
                            trigger_product_id=decision.product_id,
                            trigger_triggers=decision.panic.triggers if decision.panic else [],
                        )
                    executed_trades.append(
                        {
                            "product_id": decision.product_id,
                            "phase": decision.phase.value,
                            "result": execution_result,
                            "position_journal": self._record_position_journal(
                                now=now,
                                decision=decision,
                                approved_plan=((decision.preview or {}).get("plan") if decision.preview else {}) or {"action": "close", "coin": panic_coin},
                                review={"decision": "approve", "reason": "panic_exit"},
                                execution_result=execution_result,
                                before_position=before_position,
                                after_position=after_position,
                                success=panic_success,
                            ),
                        }
                    )
                    write_perp_dispatch_brief(
                        supervisor,
                        system_state,
                        execution_result=execution_result,
                    )
        else:
            credentials = load_coinbase_credentials()
            engine = TraderEngine(
                EngineContext(
                    runtime=runtime,
                    client=CoinbaseAdvancedClient(credentials),
                    state=self.state,
                )
            )
            decision = engine.autopilot_check(product_id)
            actions = self.plan_actions(decision, now)
            if actions:
                write_dispatch_brief(engine, decision, product_id)
                build_strategy_input(runtime, engine, self.state, now)
        results: list[dict[str, object]] = []
        action_index = 0
        while action_index < len(actions):
            action = actions[action_index]
            strategy_slot_lock_key: str | None = None
            if action.kind == "strategy" and action.reason == "routine_refresh" and action.state_mark_key:
                if not self._acquire_daily_strategy_slot_lock(action.state_mark_key, now):
                    result = {
                        "success": True,
                        "skipped": True,
                        "skip_reason": "daily_strategy_slot_locked",
                    }
                    result["kind"] = action.kind
                    result["deliver"] = action.deliver
                    result["reason"] = action.reason
                    results.append(result)
                    action_index += 1
                    continue
                strategy_slot_lock_key = action.state_mark_key
            if runtime.dispatch.market_mode == "perps" and action.kind == "trade_review" and skip_trade_review_this_round:
                result = {
                    "success": True,
                    "skipped": True,
                    "skip_reason": "strategy_refreshed_no_trade_candidate",
                }
                result["kind"] = action.kind
                result["deliver"] = action.deliver
                result["reason"] = action.reason
                results.append(result)
                action_index += 1
                continue
            try:
                if action.kind == "event" and action.deliver:
                    result = deliver_generated_message(
                        self.runner,
                        action=action,
                        now=now,
                        fallback_message=format_trade_event_message(decision, [], []),
                    )
                elif action.kind == "daily_report" and action.deliver:
                    result = deliver_generated_message(
                        self.runner,
                        action=action,
                        now=now,
                        fallback_message=format_daily_report_message(
                            now=now,
                            decision=decision,
                            strategy_doc=load_current_strategy(),
                        ),
                    )
                else:
                    result = self.runner.run(action, now=now)
                result["kind"] = action.kind
                result["deliver"] = action.deliver
                result["reason"] = action.reason
                if action.kind == "strategy" and result["success"]:
                    response_text = _extract_first_payload_text(result)
                    if response_text:
                        try:
                            result["_response_text"] = response_text
                            outcome = apply_strategy_action(
                                action=action,
                                action_result=result,
                                now=now,
                                runtime=runtime,
                                state=self.state,
                                decision=decision,
                                strategy_payload=strategy_payload,
                                system_state=system_state if runtime.dispatch.market_mode == "perps" else None,
                                supervisor=supervisor if runtime.dispatch.market_mode == "perps" else None,
                                engine=engine if runtime.dispatch.market_mode != "perps" else None,
                                parse_strategy_response_fn=parse_strategy_response,
                                save_strategy_doc_fn=save_strategy_doc,
                                load_current_strategy_fn=load_current_strategy,
                                allowed_strategy_symbols_fn=_allowed_strategy_symbols,
                                mark_strategy_fn=self._mark_strategy,
                                mark_scheduled_recheck_fn=self._mark_scheduled_recheck,
                                refresh_strategy_context_reports_fn=_refresh_strategy_context_reports,
                                strategy_update_is_material_fn=strategy_update_is_material,
                                notify_strategy_update_fn=lambda **kwargs: _notify_strategy_update(self.runner, runtime, **kwargs),
                            )
                            result.pop("_response_text", None)
                            result["strategy"] = outcome.saved_strategy
                            result["strategy_notify"] = outcome.notify_result
                            decision = outcome.decision
                            if runtime.dispatch.market_mode == "perps":
                                system_state = outcome.system_state
                                transition_context = outcome.transition_context
                                skip_trade_review_this_round = outcome.skip_trade_review_this_round
                                write_perp_dispatch_brief(
                                    supervisor,
                                    system_state,
                                    transition_context=transition_context,
                                )
                                if outcome.trade_review_deferred_reason:
                                    result["trade_review_deferred_reason"] = outcome.trade_review_deferred_reason
                                pending_trade_review = any(
                                    pending.kind == "trade_review" for pending in actions[action_index + 1 :]
                                )
                                if decision.phase == AutopilotPhase.trade and not pending_trade_review:
                                    suppressed_stale_event_count = sum(
                                        1 for pending in actions[action_index + 1 :] if pending.kind == "event"
                                    )
                                    if suppressed_stale_event_count:
                                        actions[action_index + 1 :] = [
                                            pending for pending in actions[action_index + 1 :] if pending.kind != "event"
                                        ]
                                        result["suppressed_stale_event_count"] = suppressed_stale_event_count
                                    follow_up_reason = f"strategy_updated:{decision.reason}"
                                    actions.insert(
                                        action_index + 1,
                                        DispatchAction(
                                            kind="trade_review",
                                            deliver=False,
                                            reason=follow_up_reason,
                                            message=TRADE_REVIEW_PROMPT,
                                        ),
                                    )
                                    result["triggered_follow_up_trade_review"] = True
                                    result["follow_up_trade_review_reason"] = follow_up_reason
                        except Exception as exc:  # pragma: no cover - defensive runtime path
                            result["success"] = False
                            result["strategy_error"] = str(exc)
                if runtime.dispatch.market_mode == "perps" and action.kind == "trade_review" and result["success"]:
                    response_text = _extract_first_payload_text(result)
                    if response_text:
                        try:
                            trade_review = parse_trade_review_response(response_text)
                            result["trade_review"] = trade_review.model_dump(mode="json")
                            approved_trade_plans = self._approved_trade_plans(system_state, trade_review)
                            if decision.flow_mode == EntryWorkflowMode.auto and approved_trade_plans:
                                executed_trades = self._execute_trade_batch(supervisor, approved_trade_plans, now=now)
                                execution_result = {
                                    "mode": "batch",
                                    "count": len(executed_trades),
                                    "items": executed_trades,
                                }
                            write_perp_dispatch_brief(
                                supervisor,
                                system_state,
                                transition_context=transition_context,
                                trade_review=trade_review,
                                execution_result=execution_result,
                            )
                            if self._should_emit_trade_event(decision, trade_review, approved_trade_plans, executed_trades):
                                event_result = self.runner.send_text(
                                    format_trade_event_message(
                                        decision,
                                        approved_trade_plans,
                                        executed_trades,
                                    )
                                )
                                event_result["kind"] = "event"
                                event_result["deliver"] = True
                                event_result["reason"] = decision.reason
                                results.append(event_result)
                                if event_result["success"]:
                                    self._mark_llm_trigger(now)
                        except Exception as exc:  # pragma: no cover - defensive runtime path
                            result["success"] = False
                            result["trade_review_error"] = str(exc)
            finally:
                if strategy_slot_lock_key:
                    self._release_daily_strategy_slot_lock(strategy_slot_lock_key)
            results.append(result)
            if result["success"]:
                self._mark_llm_trigger(now)
                notify_result = result.get("strategy_notify")
                if isinstance(notify_result, dict) and notify_result.get("success"):
                    self._mark_llm_trigger(now)
                if action.kind == "daily_report":
                    self._mark_daily_report(now)
            action_index += 1
        return {
            "decision": decision.model_dump(mode="json"),
            "actions": [
                {
                    "kind": action.kind,
                    "deliver": action.deliver,
                    "reason": action.reason,
                }
                for action in actions
            ],
            "results": results,
            "trade_review": trade_review.model_dump(mode="json") if trade_review else None,
            "executed_trades": executed_trades,
        }

    def run_forever(self) -> None:
        interval = max(15, self.runtime.dispatch.scan_interval_seconds)
        while True:
            try:
                self.dispatch_once()
            except Exception as exc:  # pragma: no cover - runtime resilience path
                print(f"[dispatch] iteration failed: {exc}", file=sys.stderr)
                traceback.print_exc()
            time.sleep(interval)


def build_dispatcher() -> TriggerDispatcher:
    runtime = load_runtime_config()
    state = StateStore()
    runner = OpenClawAgentRunner(runtime)
    return TriggerDispatcher(runtime=runtime, state=state, runner=runner)


def _refresh_strategy_context_reports(
    runtime: RuntimeConfig,
    state: StateStore,
    now: datetime,
    *,
    supervisor: PerpSupervisor | None = None,
    engine: TraderEngine | None = None,
) -> dict[str, object] | None:
    return refresh_strategy_context_reports(
        runtime,
        state,
        now,
        supervisor=supervisor,
        engine=engine,
        perp_supervisor_cls=PerpSupervisor,
        build_perp_engine_fn=build_perp_engine,
        load_coinbase_credentials_fn=load_coinbase_credentials,
        coinbase_client_cls=CoinbaseAdvancedClient,
        trader_engine_cls=TraderEngine,
        engine_context_cls=EngineContext,
        build_strategy_input_perps_fn=build_strategy_input_perps,
        build_strategy_input_fn=build_strategy_input,
    )


def run_strategy_refresh(
    *,
    now: datetime | None = None,
    reason: str = "manual_refresh",
    deliver: bool = False,
) -> dict[str, object]:
    def _scale_trade_plan_for_refresh(
        decision: AutopilotDecision,
        *,
        review_decision: str,
        size_scale: float,
    ) -> dict[str, Any] | None:
        return scale_trade_plan(
            decision,
            review_decision=review_decision,
            size_scale=size_scale,
            optional_decimal=_optional_decimal,
        )

    def _approved_trade_plans_for_refresh(system_state, trade_review: LlmTradeReviewDecision) -> list[dict[str, Any]]:
        return approved_trade_plans(
            system_state,
            trade_review,
            scale_trade_plan_fn=_scale_trade_plan_for_refresh,
        )

    def _record_position_journal_for_refresh(
        *,
        now: datetime,
        decision: AutopilotDecision,
        approved_plan: dict[str, Any],
        review: dict[str, Any] | None,
        execution_result: dict[str, Any] | None,
        before_position: dict[str, Any] | None,
        after_position: dict[str, Any] | None,
        success: bool,
    ) -> dict[str, Any]:
        entry = build_position_journal_entry(
            now=now,
            decision=decision,
            approved_plan=approved_plan,
            review=review,
            execution_result=execution_result,
            before_position=before_position,
            after_position=after_position,
            success=success,
            current_strategy=load_current_strategy() or {},
        )
        return append_position_journal_entry(entry)

    def _execute_trade_batch_for_refresh(supervisor, approved_trade_plans: list[dict[str, Any]], *, now: datetime):
        return execute_trade_batch(
            supervisor,
            approved_trade_plans,
            now=now,
            serialize_position_snapshot_fn=serialize_position_snapshot,
            record_position_journal_fn=_record_position_journal_for_refresh,
        )

    return run_strategy_refresh_flow(
        now=now or datetime.now(UTC),
        reason=reason,
        deliver=deliver,
        load_runtime_config_fn=load_runtime_config,
        state_factory=StateStore,
        sync_news_fn=sync_news,
        perp_supervisor_cls=PerpSupervisor,
        build_perp_engine_fn=build_perp_engine,
        write_perp_news_brief_fn=write_perp_news_brief,
        build_strategy_input_perps_fn=build_strategy_input_perps,
        load_coinbase_credentials_fn=load_coinbase_credentials,
        coinbase_client_cls=CoinbaseAdvancedClient,
        trader_engine_cls=TraderEngine,
        engine_context_cls=EngineContext,
        build_strategy_input_fn=build_strategy_input,
        runner_factory=OpenClawAgentRunner,
        strategy_prompt=STRATEGY_PROMPT,
        extract_first_payload_text_fn=_extract_first_payload_text,
        parse_strategy_response_fn=parse_strategy_response,
        save_strategy_doc_fn=save_strategy_doc,
        allowed_strategy_symbols_fn=_allowed_strategy_symbols,
        load_current_strategy_fn=load_current_strategy,
        current_strategy_schedule_slot_fn=current_strategy_schedule_slot,
        mark_strategy_regime_shift_rewrite_fn=mark_strategy_regime_shift_rewrite,
        clear_strategy_pending_regime_shift_fn=clear_strategy_pending_regime_shift,
        refresh_strategy_context_reports_fn=_refresh_strategy_context_reports,
        notify_strategy_update_fn=_notify_strategy_update,
        write_perp_dispatch_brief_fn=write_perp_dispatch_brief,
        trade_review_prompt=TRADE_REVIEW_PROMPT,
        event_prompt=EVENT_PROMPT,
        parse_trade_review_response_fn=parse_trade_review_response,
        approved_trade_plans_fn=_approved_trade_plans_for_refresh,
        execute_trade_batch_fn=_execute_trade_batch_for_refresh,
        should_emit_trade_event_fn=lambda decision, trade_review, approved_trade_plans, executed_trades: should_emit_trade_event(
            decision,
            trade_review,
            approved_trade_plans,
            executed_trades,
            market_mode="perps",
        ),
    )
