from __future__ import annotations

from datetime import datetime

from ..models import AutopilotDecision, AutopilotPhase
from .parsing import DispatchAction
from .prompts import DAILY_REPORT_PROMPT, EVENT_PROMPT, FALLBACK_PROMPT, STRATEGY_PROMPT, TRADE_REVIEW_PROMPT


def build_dispatch_actions(
    decision: AutopilotDecision,
    now: datetime,
    *,
    strategy_reason: str | None,
    strategy_mark_key: str | None,
    market_mode: str,
    enable_observe_notifications: bool,
    daily_report_due: bool,
    fallback_due: bool,
) -> list[DispatchAction]:
    actions: list[DispatchAction] = []
    if strategy_reason:
        actions.append(
            DispatchAction(
                kind="strategy",
                deliver=False,
                reason=strategy_reason,
                message=STRATEGY_PROMPT,
                state_mark_key=strategy_mark_key,
            )
        )
    if decision.phase == AutopilotPhase.trade:
        actions.append(
            DispatchAction(
                kind="trade_review",
                deliver=False,
                reason=decision.reason,
                message=TRADE_REVIEW_PROMPT,
            )
        )
    should_emit_immediate_event = (
        decision.phase != AutopilotPhase.heartbeat
        and decision.notify_user
        and not (market_mode == "perps" and decision.phase == AutopilotPhase.trade)
    )
    if decision.phase == AutopilotPhase.observe and not enable_observe_notifications:
        should_emit_immediate_event = False
    if should_emit_immediate_event:
        actions.append(
            DispatchAction(
                kind="event",
                deliver=True,
                reason=decision.reason,
                message=EVENT_PROMPT,
            )
        )
    if daily_report_due:
        actions.append(
            DispatchAction(
                kind="daily_report",
                deliver=True,
                reason="daily_report_due",
                message=DAILY_REPORT_PROMPT,
            )
        )
    if not actions and fallback_due:
        actions.append(
            DispatchAction(
                kind="fallback",
                deliver=False,
                reason="llm_fallback_due",
                message=FALLBACK_PROMPT,
            )
        )
    return actions
