from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..config import RuntimeConfig
from ..models import AutopilotPhase, EntryWorkflowMode
from .notifications import format_trade_event_message


@dataclass
class StrategyActionOutcome:
    saved_strategy: dict[str, Any]
    notify_result: dict[str, object]
    decision: Any
    system_state: Any
    transition_context: dict[str, Any] | None
    skip_trade_review_this_round: bool
    trade_review_deferred_reason: str | None = None


def allowed_strategy_symbols(runtime: RuntimeConfig) -> set[str]:
    symbols = {str(item).upper() for item in runtime.strategy.track_products}
    if runtime.dispatch.market_mode == "perps":
        symbols |= {f"{str(item).upper()}-PERP" for item in runtime.strategy.track_products}
    return symbols


def refresh_strategy_context_reports(
    runtime: RuntimeConfig,
    state,
    now: datetime,
    *,
    supervisor=None,
    engine=None,
    perp_supervisor_cls,
    build_perp_engine_fn,
    load_coinbase_credentials_fn,
    coinbase_client_cls,
    trader_engine_cls,
    engine_context_cls,
    build_strategy_input_perps_fn,
    build_strategy_input_fn,
):
    if runtime.dispatch.market_mode == "perps":
        active_supervisor = supervisor or perp_supervisor_cls(
            runtime=runtime,
            state=state,
            engine=build_perp_engine_fn(runtime, state),
        )
        return build_strategy_input_perps_fn(runtime, active_supervisor, state, now)
    if engine is None:
        credentials = load_coinbase_credentials_fn()
        engine = trader_engine_cls(
            engine_context_cls(
                runtime=runtime,
                client=coinbase_client_cls(credentials),
                state=state,
            )
        )
    return build_strategy_input_fn(runtime, engine, state, now)


def build_transition_context(previous_decision, current_decision) -> dict[str, Any] | None:
    if previous_decision is None or current_decision is None:
        return None
    previous_phase = getattr(getattr(previous_decision, "phase", None), "value", getattr(previous_decision, "phase", None))
    current_phase = getattr(getattr(current_decision, "phase", None), "value", getattr(current_decision, "phase", None))
    if previous_phase is None or current_phase is None:
        return None
    previous_reason = str(getattr(previous_decision, "reason", "") or "")
    current_reason = str(getattr(current_decision, "reason", "") or "")
    why_now_unblocked = (
        f"上一轮因 {previous_reason} 暂不执行；当前转为 {current_reason}，已满足本轮处理条件。"
        if previous_reason and current_reason and (previous_phase != current_phase or previous_reason != current_reason)
        else f"当前维持 {current_phase}，沿用 {current_reason or '当前条件'}。"
    )
    return {
        "previous_phase": str(previous_phase),
        "previous_reason": previous_reason,
        "previous_product_id": str(getattr(previous_decision, "product_id", "") or ""),
        "current_phase": str(current_phase),
        "current_reason": current_reason,
        "current_product_id": str(getattr(current_decision, "product_id", "") or ""),
        "transition": f"{previous_phase}->{current_phase}",
        "why_now_unblocked": why_now_unblocked,
    }


def apply_strategy_action(
    *,
    action,
    action_result: dict[str, object],
    now: datetime,
    runtime: RuntimeConfig,
    state,
    decision,
    strategy_payload: dict[str, object] | None,
    system_state,
    supervisor=None,
    engine=None,
    parse_strategy_response_fn,
    save_strategy_doc_fn,
    load_current_strategy_fn,
    allowed_strategy_symbols_fn,
    mark_strategy_fn,
    mark_scheduled_recheck_fn,
    refresh_strategy_context_reports_fn,
    strategy_update_is_material_fn,
    notify_strategy_update_fn,
) -> StrategyActionOutcome:
    response_text = action_result.get("_response_text")
    if not response_text:
        raise ValueError("strategy action missing response text")
    previous_strategy = load_current_strategy_fn()
    parsed = parse_strategy_response_fn(
        response_text,
        now=now,
        strategy_date=now.astimezone(ZoneInfo(runtime.strategy.timezone)).date().isoformat(),
        reason=action.reason,
        allowed_symbols=allowed_strategy_symbols_fn(runtime),
        recommended_limits=(
            strategy_payload.get("recommended_limits", {})
            if runtime.dispatch.market_mode == "perps" and isinstance(strategy_payload, dict)
            else None
        ),
        current_strategy=previous_strategy,
    )
    saved = save_strategy_doc_fn(parsed, now)
    fingerprint = None
    if getattr(decision, "latest_news", None):
        item = decision.latest_news[0]
        fingerprint = f"{item.source}|{item.title}|{item.url}"
    mark_strategy_fn(now, fingerprint=fingerprint, reason=action.reason)
    mark_scheduled_recheck_fn(action.state_mark_key, now)
    refresh_strategy_context_reports_fn(
        runtime,
        state,
        now,
        supervisor=supervisor if runtime.dispatch.market_mode == "perps" else None,
        engine=engine if runtime.dispatch.market_mode != "perps" else None,
    )

    next_system_state = system_state
    next_decision = decision
    transition_context = None
    skip_trade_review_this_round = False
    trade_review_deferred_reason = None
    if runtime.dispatch.market_mode == "perps":
        try:
            next_system_state = supervisor.system_state()
            next_decision = next_system_state.primary
            transition_context = build_transition_context(decision, next_decision)
            skip_trade_review_this_round = next_decision.phase != AutopilotPhase.trade
        except Exception as exc:
            skip_trade_review_this_round = True
            trade_review_deferred_reason = f"strategy_refreshed_recheck_failed:{exc}"

    material = strategy_update_is_material_fn(
        previous_strategy,
        saved,
        runtime.strategy,
        reason=action.reason,
    )
    if material:
        notify_result = notify_strategy_update_fn(
            now=now,
            reason=f"strategy_updated:{action.reason}",
            strategy_doc=saved,
        )
    else:
        notify_result = {
            "success": True,
            "skipped": True,
            "reason": "no_material_change",
        }
    return StrategyActionOutcome(
        saved_strategy=saved,
        notify_result=notify_result,
        decision=next_decision,
        system_state=next_system_state,
        transition_context=transition_context,
        skip_trade_review_this_round=skip_trade_review_this_round,
        trade_review_deferred_reason=trade_review_deferred_reason,
    )


def run_strategy_refresh_flow(
    *,
    now: datetime,
    reason: str,
    deliver: bool,
    load_runtime_config_fn,
    state_factory,
    sync_news_fn,
    perp_supervisor_cls,
    build_perp_engine_fn,
    write_perp_news_brief_fn,
    build_strategy_input_perps_fn,
    load_coinbase_credentials_fn,
    coinbase_client_cls,
    trader_engine_cls,
    engine_context_cls,
    build_strategy_input_fn,
    runner_factory,
    strategy_prompt: str,
    extract_first_payload_text_fn,
    parse_strategy_response_fn,
    save_strategy_doc_fn,
    allowed_strategy_symbols_fn,
    load_current_strategy_fn,
    current_strategy_schedule_slot_fn,
    mark_strategy_regime_shift_rewrite_fn,
    clear_strategy_pending_regime_shift_fn,
    refresh_strategy_context_reports_fn,
    notify_strategy_update_fn,
    write_perp_dispatch_brief_fn,
    trade_review_prompt: str,
    event_prompt: str,
    parse_trade_review_response_fn,
    approved_trade_plans_fn,
    execute_trade_batch_fn,
    should_emit_trade_event_fn,
) -> dict[str, object]:
    runtime = load_runtime_config_fn()
    perps_mode = getattr(runtime.perps.mode, "value", runtime.perps.mode)
    if (
        runtime.dispatch.market_mode == "perps"
        and str(perps_mode).lower() == "live"
        and reason.startswith("manual_")
        and not deliver
    ):
        return {
            "success": False,
            "blocked": True,
            "reason": "manual_live_strategy_refresh_requires_delivery",
            "error": "Manual live strategy refresh without delivery is blocked to avoid silently overriding the active strategy.",
        }
    state = state_factory()
    sync_news_fn(runtime.news, state, now=now)
    strategy_payload: dict[str, object] | None = None
    supervisor = None
    engine = None
    previous_decision = None
    if runtime.dispatch.market_mode == "perps":
        supervisor = perp_supervisor_cls(
            runtime=runtime,
            state=state,
            engine=build_perp_engine_fn(runtime, state),
        )
        try:
            previous_decision = supervisor.system_state().primary
        except Exception:
            previous_decision = None
        write_perp_news_brief_fn(supervisor)
        strategy_payload = build_strategy_input_perps_fn(runtime, supervisor, state, now)
    else:
        credentials = load_coinbase_credentials_fn()
        engine = trader_engine_cls(
            engine_context_cls(
                runtime=runtime,
                client=coinbase_client_cls(credentials),
                state=state,
            )
        )
        build_strategy_input_fn(runtime, engine, state, now)
    runner = runner_factory(runtime)
    from .parsing import DispatchAction

    action = DispatchAction(
        kind="strategy",
        deliver=False,
        reason=reason,
        message=strategy_prompt,
    )
    result = runner.run(action)
    response_text = extract_first_payload_text_fn(result)
    if not result.get("success") or not response_text:
        return result
    try:
        parsed = parse_strategy_response_fn(
            response_text,
            now=now,
            strategy_date=now.astimezone(ZoneInfo(runtime.strategy.timezone)).date().isoformat(),
            reason=reason,
            allowed_symbols=allowed_strategy_symbols_fn(runtime),
            recommended_limits=(
                strategy_payload.get("recommended_limits", {})
                if runtime.dispatch.market_mode == "perps" and isinstance(strategy_payload, dict)
                else None
            ),
            current_strategy=load_current_strategy_fn(),
        )
        saved = save_strategy_doc_fn(parsed, now)
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "raw": result,
        }
    state.set_value("strategy:last_updated_at", now.astimezone(UTC).isoformat())
    state.set_value("strategy:last_strategy_date", now.astimezone(ZoneInfo(runtime.strategy.timezone)).date().isoformat())
    slot_key = current_strategy_schedule_slot_fn(runtime.strategy, now)
    if slot_key:
        state.set_value("strategy:last_strategy_slot", slot_key, now=now)
    if str(reason).strip().lower().startswith("regime_shift:"):
        mark_strategy_regime_shift_rewrite_fn(state, now)
    clear_strategy_pending_regime_shift_fn(state)
    refresh_strategy_context_reports_fn(
        runtime,
        state,
        now,
        supervisor=supervisor if runtime.dispatch.market_mode == "perps" else None,
        engine=engine if runtime.dispatch.market_mode != "perps" else None,
    )
    if deliver:
        notify_result = notify_strategy_update_fn(
            runner,
            runtime,
            now=now,
            reason=f"strategy_updated:{reason}",
            strategy_doc=saved,
        )
    else:
        notify_result = {
            "success": True,
            "skipped": True,
            "reason": "delivery_disabled",
        }
    trade_review = None
    executed_trades: list[dict[str, object]] = []
    decision_payload: dict[str, object] | None = None
    results: list[dict[str, object]] = []
    if runtime.dispatch.market_mode == "perps" and supervisor is not None:
        try:
            system_state = supervisor.system_state()
            decision = system_state.primary
            transition_context = build_transition_context(previous_decision, decision)
            decision_payload = decision.model_dump(mode="json")
            write_perp_dispatch_brief_fn(supervisor, system_state, transition_context=transition_context)
            if decision.phase == AutopilotPhase.trade:
                trade_action_result = runner.run(
                    DispatchAction(
                        kind="trade_review",
                        deliver=False,
                        reason=f"strategy_updated:{decision.reason}",
                        message=trade_review_prompt,
                    )
                )
                trade_action_result["kind"] = "trade_review"
                trade_action_result["deliver"] = False
                trade_action_result["reason"] = f"strategy_updated:{decision.reason}"
                results.append(trade_action_result)
                response_text = extract_first_payload_text_fn(trade_action_result)
                if trade_action_result.get("success") and response_text:
                    trade_review = parse_trade_review_response_fn(response_text)
                    approved_trade_plans = approved_trade_plans_fn(system_state, trade_review)
                    execution_result = None
                    if decision.flow_mode == EntryWorkflowMode.auto and approved_trade_plans:
                        executed_trades = execute_trade_batch_fn(supervisor, approved_trade_plans, now=now)
                        execution_result = {
                            "mode": "batch",
                            "count": len(executed_trades),
                            "items": executed_trades,
                        }
                    write_perp_dispatch_brief_fn(
                        supervisor,
                        system_state,
                        transition_context=transition_context,
                        trade_review=trade_review,
                        execution_result=execution_result,
                    )
                    if should_emit_trade_event_fn(decision, trade_review, approved_trade_plans, executed_trades):
                        event_result = runner.send_text(
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
        except Exception as exc:
            results.append(
                {
                    "kind": "trade_review",
                    "deliver": False,
                    "reason": "strategy_refresh_follow_up_skipped",
                    "success": True,
                    "skipped": True,
                    "skip_reason": f"strategy_refresh_follow_up_failed:{exc}",
                }
            )
    return {
        "success": True,
        "strategy": saved,
        "raw": result,
        "strategy_notify": notify_result,
        "decision": decision_payload,
        "trade_review": trade_review.model_dump(mode="json") if trade_review else None,
        "executed_trades": executed_trades,
        "results": results,
    }
