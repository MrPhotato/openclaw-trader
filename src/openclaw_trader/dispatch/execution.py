from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable

from ..models import AutopilotDecision


def serialize_position_snapshot(account: Any) -> dict[str, Any] | None:
    if account is None:
        return None
    position = getattr(account, "position", None)
    if position is None:
        return None
    if isinstance(position, dict):
        return dict(position)
    if hasattr(position, "model_dump"):
        return position.model_dump(mode="json")
    return None


def build_position_journal_entry(
    *,
    now: datetime,
    decision: AutopilotDecision,
    approved_plan: dict[str, Any],
    review: dict[str, Any] | None,
    execution_result: dict[str, Any] | None,
    before_position: dict[str, Any] | None,
    after_position: dict[str, Any] | None,
    success: bool,
    current_strategy: dict[str, Any],
) -> dict[str, Any]:
    return {
        "journaled_at": now.astimezone(UTC).isoformat(),
        "product_id": decision.product_id,
        "coin": decision.product_id.split("-")[0],
        "phase": decision.phase.value,
        "flow_mode": decision.flow_mode.value,
        "decision_reason": decision.reason,
        "signal_side": decision.signal.side.value if decision.signal else None,
        "signal_confidence": decision.signal.confidence if decision.signal else None,
        "strategy_version": current_strategy.get("version"),
        "strategy_change_reason": current_strategy.get("change_reason"),
        "approved_plan": approved_plan,
        "review": review or {},
        "review_reason": (review or {}).get("reason"),
        "before_position": before_position,
        "after_position": after_position,
        "success": success,
        "execution_result": execution_result,
    }


def execute_trade_batch(
    supervisor,
    approved_trade_plans: list[dict[str, Any]],
    *,
    now: datetime,
    serialize_position_snapshot_fn: Callable[[Any], dict[str, Any] | None],
    record_position_journal_fn: Callable[..., dict[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in approved_trade_plans:
        decision = item["decision"]
        plan = item["plan"]
        coin = str(plan.get("coin", decision.product_id.split("-")[0])).upper()
        before_account = supervisor.engine.account(coin)
        before_position = serialize_position_snapshot_fn(before_account)
        try:
            execution_result = supervisor.apply_trade_plan(decision, plan_override=plan)
            after_account = supervisor.engine.account(coin)
            after_position = serialize_position_snapshot_fn(after_account)
            success = bool(
                execution_result
                and all(step.get("success", False) for step in execution_result.get("results", []))
            )
            result_entry = {
                "product_id": decision.product_id,
                "phase": decision.phase.value,
                "approved_plan": plan,
                "review": item["review"],
                "result": execution_result,
                "success": success,
                "position_journal": record_position_journal_fn(
                    now=now,
                    decision=decision,
                    approved_plan=plan,
                    review=item["review"],
                    execution_result=execution_result,
                    before_position=before_position,
                    after_position=after_position,
                    success=success,
                ),
            }
            if execution_result is None:
                result_entry["error"] = "execution_returned_none"
                result_entry["success"] = False
            results.append(result_entry)
        except Exception as exc:  # pragma: no cover - defensive runtime path
            results.append(
                {
                    "product_id": decision.product_id,
                    "phase": decision.phase.value,
                    "approved_plan": plan,
                    "review": item["review"],
                    "result": None,
                    "success": False,
                    "error": str(exc),
                    "position_journal": record_position_journal_fn(
                        now=now,
                        decision=decision,
                        approved_plan=plan,
                        review=item["review"],
                        execution_result=None,
                        before_position=before_position,
                        after_position=before_position,
                        success=False,
                    ),
                }
            )
    return results
