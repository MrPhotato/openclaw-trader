---
name: risk-trader-decision
description: Risk Trader execution decision workflow for openclaw-trader. Use when RT is awakened by a condition trigger, heartbeat fallback, or explicit operator request to evaluate strategy, market, news, execution memory, and risk facts, then emit a pure JSON execution submission.
---

# Risk Trader Decision

Use this skill for `RT` work only.

## Use When
- Standard path: condition-triggered RT wakeup via Workflow Orchestrator calling the registered OpenClaw RT cron job.
- Fallback path: low-frequency heartbeat when no stronger trigger arrives.
- Typical triggers:
  - new PM strategy
  - `policy_risk` state change
  - execution failure or abnormality
  - `MEA` `high` event reminder
  - market structure change
  - exposure drift
  - execution follow-up after real fills

## Job
- Pull exactly one RT runtime pack from `agent_gateway`.
- Let the helper generate the round's default submission scaffold, then edit that scaffold instead of composing the JSON from scratch.
- Read `trigger_delta` and `standing_tactical_map` before raw context traversal.
- Read `rt_decision_digest` first and treat it as the default working view for this turn.
- Convert PM intent into a multi-symbol execution decision batch.
- Operate inside PM and risk boundaries.
- Escalate to PM when current market makes the strategy hard to apply.
- For official condition-triggered, heartbeat, or PM follow-up work, submit one `execution` decision batch through the submit bridge with the current `input_id` and `live=true`.
- Only include `max_notional_usd` when the user or upstream trigger explicitly asks for a temporary execution cap.
- If PM currently has an active, unlocked target on a symbol where the desk is still unpositioned or pointed the wrong way, this round must do one of two things: place the first entry/flip decision, or raise a root-level `pm_recheck_requested=true` with a concrete `pm_recheck_reason`. Do not hide behind repeated all-`wait` batches.
- If you refresh the tactical map for such a symbol, the map must explicitly include `first_entry_plan`. A map that only says "wait for confirmation" is incomplete.

## Workflow
1. Read [runtime-inputs.md](references/runtime-inputs.md) to understand the current payload and the target chain.
2. Read `trigger_delta`, then `standing_tactical_map`, then `rt_decision_digest`. Do not start by manually traversing the full runtime pack.
3. Reuse the helper-generated `/tmp/rt_execution_submission.json` scaffold for this round. Only rebuild the whole JSON batch by hand if the helper is unavailable.
4. Follow [three-stage-funnel.md](references/three-stage-funnel.md) in order.
5. Only drill into raw `execution_contexts`, `market.market_context`, `recent_execution_thoughts`, or `news_events` when the digest leaves a material ambiguity.
6. Apply [escalation-and-boundaries.md](references/escalation-and-boundaries.md).
7. If `trigger_delta.requires_tactical_map_refresh = true`, the scaffold must already contain `tactical_map_update`; fill it in instead of deleting it.
8. Emit formal JSON using [formal-output.md](references/formal-output.md), and carry the current `input_id` back to the submit bridge.

## Guardrails
- Default to Chinese for all non-JSON commentary unless a downstream contract explicitly requires another language.
- Pull the RT runtime pack with one correct `POST` only. Do not probe the endpoint with a preliminary `GET`.
- Prefer saving the RT runtime pack to a temp file and reading the fields you need from that file instead of pasting the full JSON pack back into the session.
- Prefer editing the helper-generated `/tmp/rt_execution_submission.json` scaffold instead of writing a fresh JSON batch by hand.
- Keep the scaffold file as a pure root-level `ExecutionSubmission` object. Do not insert wrapper fields such as `input_id`, `trace_id`, `agent_role`, `task_kind`, `pm_recheck_request`, `rt_commentary`, or per-decision `execution_params`.
- Default to the map-first path: `trigger_delta -> standing_tactical_map -> rt_decision_digest -> targeted drill-down -> submit`.
- If `standing_tactical_map` is null and `trigger_delta.requires_tactical_map_refresh = true`, you must refresh the map in the same `execution` submission via `tactical_map_update`.
- If the desk is still unpositioned or pointed the wrong way on an active, unlocked symbol, treat `wait` as an exception path that requires root-level PM escalation. It is not your default posture.
- Do not rewrite the tactical map on ordinary no-op / heartbeat rounds unless the runtime pack explicitly indicates a refresh is required or you are making a materially new tactical call.
- No long-term memory or recall.
- Do not redefine portfolio direction.
- Do not bypass `policy_risk`.
- Do all RT work in the current session. Do not use `sessions_spawn`, subagents, or child sessions to fetch runtime packs, think, or stage execution decisions.
- If you need to contact PM, MEA, or Chief, use `sessions_send` directly to their main session. Do not create helper sessions.
- Do not decide exchange mechanics; execution sends orders after approval.
- Do not redesign order routing, retry policy, fill handling, or exchange-specific parameters. Those belong downstream in `Trade Gateway.execution`.
- **Account state source of truth:** Always get positions/equity from `/api/agent/pull/rt` runtime pack (`market.portfolio`, `market.accounts`). Do NOT use `otrader portfolio` or other CLI commands due to caching issues.
- **Exposure algorithm source of truth:** Treat exposure share as `% of exposure budget`, where exposure budget = `total_equity_usd * max_leverage`. Do not fall back to the old `% of equity` mental model.
- If the runtime pack already gives you normalized exposure/share fields, use those fields directly. Do not manually recompute exposure share from `current_notional_usd / total_equity_usd`.
- A quick sanity check: if notional is about `$233` and equity is about `$982` with `5x` max leverage, the correct exposure share is about `4.76%`, not `23.8%`.
- Formal `execution` submission must be JSON only, with no markdown fence or prose wrapper.
- Submit the decision batch at the root level. Do not wrap it under `execution`, `payload.execution`, or any other nested object.
- RT submits `decisions[]`, not `orders[]`, `execution.summary`, or exchange-specific order plans.
- If you decide to take no action this round, that is only allowed when there is no active unlocked entry gap, or when you also raise root-level `pm_recheck_requested=true` with a concrete reason. Otherwise `decisions: []` is avoidance, not discipline.
- If you want to explicitly maintain an existing position unchanged, use action `hold`. `hold` is a no-op signal and must not be used to create or resize a position.

## References
- [runtime-inputs.md](references/runtime-inputs.md)
- [three-stage-funnel.md](references/three-stage-funnel.md)
- [formal-output.md](references/formal-output.md)
- [escalation-and-boundaries.md](references/escalation-and-boundaries.md)
