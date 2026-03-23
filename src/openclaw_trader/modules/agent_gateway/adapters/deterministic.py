from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from ....shared.utils import new_id
from ...agent_gateway.models import AgentReply, AgentTask


class DeterministicAgentRunner:
    def run(self, task: AgentTask) -> AgentReply:
        if task.task_kind == "retro_turn":
            round_index = int(task.payload.get("round_index") or 1)
            speaker_role = str(task.payload.get("speaker_role") or task.agent_role)
            statements = {
                "pm": f"round_{round_index}_pm: target and thesis still align with the observed market path.",
                "risk_trader": f"round_{round_index}_rt: execution quality was acceptable and no boundary breach was needed.",
                "macro_event_analyst": f"round_{round_index}_mea: event flow did not invalidate the current thesis.",
                "crypto_chief": f"round_{round_index}_chief: keep discussion disciplined and isolate process from luck.",
            }
            return AgentReply(
                task_id=task.task_id,
                agent_role=task.agent_role,
                status="completed",
                payload={
                    "speaker_role": speaker_role,
                    "statement": statements.get(task.agent_role, f"round_{round_index}_{task.agent_role}: no new objection."),
                },
            )
        if task.agent_role == "risk_trader":
            context = task.payload
            execution_contexts = context.get("execution_contexts") or []
            decisions: list[dict] = []
            for index, item in enumerate(execution_contexts, start=1):
                if not isinstance(item, dict):
                    continue
                target = item.get("target") or {}
                symbol = str(target.get("symbol") or item.get("coin") or "").upper()
                if not symbol:
                    continue
                state = str(target.get("state") or "watch")
                direction = str(target.get("direction") or "flat")
                current_share = float(item.get("current_position_share_pct") or 0.0)
                band = target.get("target_exposure_band_pct") or [0.0, 0.0]
                band_high = float(band[1] if len(band) > 1 else band[0] if band else 0.0)
                action = "wait"
                size_pct = 0.0
                if state == "active" and direction in {"long", "short"} and current_share < band_high:
                    action = "open" if current_share == 0 else "add"
                    size_pct = round(min(max(band_high - current_share, 0.0), 3.0), 2)
                elif state in {"only_reduce", "disabled"} and current_share > 0:
                    action = "reduce"
                    size_pct = round(min(current_share, 2.0), 2)
                decisions.append(
                    {
                        "symbol": symbol,
                        "action": action,
                        "direction": direction,
                        "reason": f"deterministic_rt_{action}",
                        "size_pct_of_equity": size_pct if action != "wait" else 0.0,
                        "priority": index,
                        "urgency": "normal" if action != "wait" else "low",
                        "valid_for_minutes": 10,
                        "escalate_to_pm": False,
                    }
                )
            return AgentReply(
                task_id=task.task_id,
                agent_role=task.agent_role,
                status="completed",
                payload={
                    "decision_id": new_id("decision"),
                    "strategy_id": (task.payload.get("strategy") or {}).get("strategy_id"),
                    "generated_at_utc": datetime.now(UTC).isoformat(),
                    "trigger_type": "deterministic_runtime",
                    "decisions": decisions,
                },
            )
        if task.agent_role == "pm":
            context = task.payload
            market = context.get("market") or {}
            news_events = context.get("news_events") or []
            forecasts = context.get("forecasts") or {}
            targets: list[dict] = []
            target_total = 0.0
            portfolio_mode = "normal"
            if any(str(item.get("severity") or item.get("impact_level") or "").lower() == "high" for item in news_events if isinstance(item, dict)):
                portfolio_mode = "defensive"
            for index, coin in enumerate(sorted((market.get("market") or {}).keys()), start=1):
                horizons = forecasts.get(coin, {})
                four_hour = str((horizons.get("4h") or {}).get("side") or "flat")
                twelve_hour = str((horizons.get("12h") or {}).get("side") or "flat")
                state = "watch"
                direction = "flat"
                band = [0.0, 0.0]
                if portfolio_mode != "defensive" and four_hour == "long" and twelve_hour == "long":
                    state = "active"
                    direction = "long"
                    band = [1.0, 3.0] if coin == "BTC" else [0.0, 2.0]
                targets.append(
                    {
                        "symbol": coin,
                        "state": state,
                        "direction": direction,
                        "target_exposure_band_pct": band,
                        "rt_discretion_band_pct": 1.0,
                        "priority": index,
                    }
                )
                target_total += band[1]
            return AgentReply(
                task_id=task.task_id,
                agent_role=task.agent_role,
                status="completed",
                payload={
                    "portfolio_mode": portfolio_mode,
                    "target_gross_exposure_band_pct": [0.0, round(target_total, 2)],
                    "portfolio_thesis": "deterministic_pm_strategy",
                    "portfolio_invalidation": "invalidated_on_policy_breaker",
                    "change_summary": "deterministic_strategy_refresh",
                    "targets": targets,
                    "scheduled_rechecks": [
                        {
                            "recheck_at_utc": (datetime.now(UTC) + timedelta(hours=4)).isoformat(),
                            "scope": "portfolio",
                            "reason": "deterministic_recheck",
                        }
                    ],
                },
            )
        if task.agent_role == "macro_event_analyst":
            events = []
            for item in task.payload.get("news_events") or []:
                if not isinstance(item, dict):
                    continue
                severity = str(item.get("severity") or "low").lower()
                impact = "high" if severity == "high" else "medium" if severity == "medium" else "low"
                title = str(item.get("title") or "macro_event")
                events.append(
                    {
                        "event_id": item.get("news_id") or new_id("macro_event"),
                        "category": "macro" if "macro" in title.lower() else "market",
                        "summary": title[:140],
                        "impact_level": impact,
                    }
                )
            return AgentReply(
                task_id=task.task_id,
                agent_role=task.agent_role,
                status="completed",
                payload={
                    "events": events,
                },
            )
        if task.agent_role == "crypto_chief":
            learning_results = []
            for target in list(task.payload.get("learning_targets") or []):
                if not isinstance(target, dict):
                    continue
                agent_role = str(target.get("agent_role") or "").strip()
                learning_path = str(target.get("learning_path") or "").strip()
                if not agent_role or not learning_path:
                    continue
                learning_summary = f"{agent_role} captured one deterministic retro lesson."
                path = Path(learning_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(f"- {learning_summary}\n")
                learning_results.append(
                    {
                        "agent_role": agent_role,
                        "learning_updated": True,
                        "learning_path": learning_path,
                        "learning_summary": learning_summary,
                    }
                )
            return AgentReply(
                task_id=task.task_id,
                agent_role=task.agent_role,
                status="completed",
                payload={
                    "owner_summary": "Deterministic retro completed. Strategy, execution and macro flows were reviewed.",
                    "reset_command": "/new",
                    "learning_completed": True,
                    "learning_results": learning_results,
                },
            )
        return AgentReply(task_id=task.task_id, agent_role=task.agent_role, status="completed", payload={"decision": "observe"})


class DeterministicSessionController:
    def reset(self, *, agent_role: str, session_id: str, reset_command: str = "/new") -> dict[str, object]:
        return {
            "agent_role": agent_role,
            "session_id": session_id,
            "reset_command": reset_command,
            "success": True,
            "mode": "deterministic",
        }
