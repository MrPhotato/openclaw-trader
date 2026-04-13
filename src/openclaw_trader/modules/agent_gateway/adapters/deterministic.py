from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from ....shared.utils import new_id
from ...agent_gateway.models import AgentReply, AgentTask


class DeterministicAgentRunner:
    def run(self, task: AgentTask) -> AgentReply:
        if task.task_kind == "retro_brief":
            focus = {
                "pm": (
                    "PM 对 band 和 thesis 仍偏保守，导致风险利用率不足。",
                    "RT 需要在机会窗口里更主动加风险，而不是等到确认过多后再动。",
                    "PM 没把翻向和恢复条件写得足够可交易。",
                    "明天把 band 调整条件和 flip triggers 写得更清楚。",
                ),
                "risk_trader": (
                    "RT 在有把握的窗口里仍偏等待，战术推进不够激进。",
                    "PM 给出的可执行边界还不够清晰，导致 RT 更容易退回 wait/hold。",
                    "RT 自己过度依赖确认，少做了先手战术动作。",
                    "明天在高把握结构里更主动使用 add/reduce，而不是只会 long 到 flat。",
                ),
                "macro_event_analyst": (
                    "MEA 的提醒密度影响了 PM 的节奏，状态变化和重复强化没有分开。",
                    "PM 应只在真正状态变化时被打断，而不是被同主题连环轰炸。",
                    "MEA 对同主题重复提醒过滤得不够严格。",
                    "明天只在状态变化时升级 PM，其余继续写入事件层。",
                ),
            }
            root_cause, challenge, self_critique, tomorrow_change = focus.get(
                task.agent_role,
                (
                    "今天没有显著 alpha，主要是流程保守。",
                    "别的角色没有把约束写清楚。",
                    "自己的复盘不够锋利。",
                    "明天把复盘结论写得更可执行。",
                ),
            )
            return AgentReply(
                task_id=task.task_id,
                agent_role=task.agent_role,
                status="completed",
                payload={
                    "root_cause": root_cause,
                    "cross_role_challenge": challenge,
                    "self_critique": self_critique,
                    "tomorrow_change": tomorrow_change,
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
                current_share = float(item.get("current_position_share_pct_of_exposure_budget") or 0.0)
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
                        "size_pct_of_exposure_budget": size_pct if action != "wait" else 0.0,
                        "priority": index,
                        "urgency": "normal" if action != "wait" else "low",
                        "valid_for_minutes": 10,
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
            high_count = sum(
                1
                for item in news_events
                if isinstance(item, dict)
                and str(item.get("severity") or item.get("impact_level") or "").lower() == "high"
            )
            if high_count >= 3:
                portfolio_mode = "defensive"
            elif high_count >= 1:
                portfolio_mode = "cautious"
            for index, coin in enumerate(sorted((market.get("market") or {}).keys()), start=1):
                horizons = forecasts.get(coin, {})
                four_hour = str((horizons.get("4h") or {}).get("side") or "flat")
                twelve_hour = str((horizons.get("12h") or {}).get("side") or "flat")
                state = "watch"
                direction = "flat"
                band = [0.0, 0.0]
                if portfolio_mode == "defensive":
                    pass
                elif four_hour in {"long", "short"} and twelve_hour == four_hour:
                    state = "active"
                    direction = four_hour
                    band = [1.0, 3.0] if coin == "BTC" else [0.0, 2.0]
                elif four_hour in {"long", "short"} and twelve_hour != ("short" if four_hour == "long" else "long"):
                    state = "active"
                    direction = four_hour
                    band = [0.0, 2.0] if coin == "BTC" else [0.0, 1.0]
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
                    "flip_triggers": "flip_to_short_on_multi_horizon_breakdown_or_hard_macro_regime_shift",
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
            _structural_keywords = {"rate", "fomc", "cpi", "regulation", "ban", "hack", "exploit", "delist", "halt"}
            for item in task.payload.get("news_events") or []:
                if not isinstance(item, dict):
                    continue
                severity = str(item.get("severity") or "low").lower()
                title = str(item.get("title") or "macro_event")
                title_lower = title.lower()
                if severity == "high" and not any(kw in title_lower for kw in _structural_keywords):
                    severity = "medium"
                impact = "high" if severity == "high" else "medium" if severity == "medium" else "low"
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
            if task.payload.get("mode") == "retro_synthesis":
                return AgentReply(
                    task_id=task.task_id,
                    agent_role=task.agent_role,
                    status="completed",
                    payload={
                        "case_id": dict(task.payload.get("retro_case") or {}).get("case_id"),
                        "owner_summary": "Chief 裁决：今天没到 1% 的主因是 PM 防守过重、RT 机会窗口推进偏慢、MEA 对重复主题过滤不够。",
                        "learning_completed": False,
                        "root_cause_ranking": [
                            "PM 风险利用率压得过低",
                            "RT 在确认过多后才推进战术动作",
                            "MEA 对同主题重复提醒过滤不够",
                        ],
                        "role_judgements": {
                            "pm": "方向判断大体合理，但 band 和翻向条件不够锋利。",
                            "risk_trader": "执行纪律稳定，但主动性不足。",
                            "macro_event_analyst": "信息质量尚可，但升级门槛不够克制。",
                        },
                        "learning_directives": [
                            {
                                "agent_role": "pm",
                                "directive": "把 risk-off 和重新加风险的条件写得更明确，尤其是 flip triggers。",
                                "rationale": "PM 的边界模糊会直接压缩 RT 的执行空间。",
                            },
                            {
                                "agent_role": "risk_trader",
                                "directive": "在高把握结构里更主动推进 add/reduce，不要总是等到确认过满。",
                                "rationale": "RT 这轮主要损失在窗口利用率，而不是方向错误。",
                            },
                            {
                                "agent_role": "macro_event_analyst",
                                "directive": "只有状态变化才打断 PM，同主题重复强化继续留在事件层。",
                                "rationale": "MEA 的过密提醒会把 PM 推向不必要的频繁改 band。",
                            },
                            {
                                "agent_role": "crypto_chief",
                                "directive": "继续把 retro 从同步会议收成异步 artifact 链。",
                                "rationale": "Chief 的价值在裁决，不在主持脆弱的同步会场。",
                            },
                        ],
                    },
                )
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
