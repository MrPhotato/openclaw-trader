# Dispatch and Sessions

## Scope

This document describes how the trader runtime decides *when* an agent
(PM / RT / MEA / Chief) should wake up, *which* session it lands in, and
*how* notifications make it back to the owner. Authoritative code is in
`src/openclaw_trader/modules/workflow_orchestrator/` and
`src/openclaw_trader/modules/agent_gateway/`.

## The Workflow Orchestrator (WO) Scheduler

WO is an in-process cycling component hosted by the FastAPI service. It
runs independently of OpenClaw's own cron and owns all automated agent
wakes. The implementation is layered deliberately:

### Layer 1 — `AgentDispatcher`

`modules/workflow_orchestrator/agent_dispatch.py`. Thin wrapper around
two subprocess primitives:

- `send_to_session(agent, session_key, message, …)`
  → `openclaw agent --agent <X> --session-id <session_key> --message <msg>`
  detached subprocess. This is how **every** PM wake reaches the agent.
- `run_cron_job_detached(job_id)`
  → `openclaw cron run <job_id>`. Still used for the RT cron-isolated
  trigger path.
- `fetch_cron_job_payload_message(job_id)`
  → reads a cron job's payload via `openclaw cron list --all --json`,
  returning the message template. Lets WO reuse the cron job definition
  as a reusable prompt while delivering it into the agent's persistent
  main session instead of an isolated cron-run.

### Layer 2 — Specialised Monitors

Each monitor owns one wake concern, runs its own background thread via
`WorkflowOrchestratorService.start()`, and calls Layer 1 to dispatch.

- `PMRecheckMonitor` (`pm_recheck.py`) — scans PM's `scheduled_rechecks`
  from the latest strategy. When one comes due it resolves the PM job's
  payload message and `send_to_session(agent="pm", session_key="agent:pm:main", …)`.
  De-duplicates via `completed_recheck_keys` persisted in the
  `pm_recheck_state` asset.
- `RTTriggerMonitor` (`rt_trigger.py`) — fires RT on condition triggers
  (strategy revision, headline-risk shifts, exposure drift, heartbeat,
  execution follow-up). Currently still dispatches via
  `openclaw cron run <rt_job_id>` for compatibility; everything else has
  moved to the main-session model.
- `RiskBrakeMonitor` (`risk_brake.py`) — watches drawdown thresholds
  from `policy_risk`. On trigger it both enforces reduce/exit orders and
  wakes **PM** through `send_to_session(agent="pm", session_key="agent:pm:main")`
  with the configured payload template, plus RT via cron. When PM later
  submits a new strategy (strategy_key changes), the same monitor
  clears `position_locks` / `portfolio_lock` from `risk_brake_state`.
- `RetroPrepMonitor` (`retro_prep.py`) — at the retro prep hour it
  prepares briefs from the three acting agents and only then wakes
  Chief. Chief's own openclaw cron job is intentionally disabled so the
  retro always fires after briefs are ready.

### Layer 3 — `AgentWakeMonitor` (generic, rule-driven)

`modules/workflow_orchestrator/agent_wake.py`. A predicate-based
scheduler meant to absorb recurring "wake this agent when X" rules
without adding another bespoke monitor. Rules live in
`dispatch.yaml` under `agent_wake_rules`. Each rule declares:

- `agent`, `target_session_key`
- `message_source` (currently `cron_job_payload` — reuse a cron job's
  message template as the wake prompt)
- `fire_when_any_of` — predicate list. Supported:
  - `cron_time` — subset cron with `minute hour * * *` (UTC/tz-aware)
  - `max_silence_since` — measure against an asset (e.g.
    `last_strategy_submit` hours since the latest strategy)
- `cooldown_minutes` — post-fire lockout

Semantics are defensive: the first scan after a cold start only records
the baseline timestamp without firing. Subsequent scans fire when the
predicate's candidate moment falls in `(last_eval_at, current]`. State
lives in the singleton `agent_wake_state` asset.

Current live rule: `pm_main_heartbeat` — 01 UTC daily + 12 h silence
fallback → wakes PM into `agent:pm:main` using the PM cron job payload.

## Session Keys as a Contract

Every automated wake path lands in a **stable, persistent session key**
so the receiving agent always sees its prior context:

- `agent:pm:main`
- `agent:risk-trader:main`
- `agent:macro-event-analyst:main`
- `agent:crypto-chief:main`

`send_to_session` passes this as `--session-id`, not as a free-text
label. If a session with that key exists, the message queues into it;
otherwise OpenClaw creates one.

This replaces an older model where each automated wake spawned a
fresh `agent:<role>:cron:<job-id>` session. That model lost PM's
running context on every fire. Under the new model:

- PM queues are fine — a backlogged PM is usually already doing the
  right thing mid-turn; dropping or skipping wakes loses information.
- Dedupe is the monitor's job (via state assets), not the session's.
- `sessions_send` from one agent to another (RT→PM, MEA→PM) lands in
  the same main session as a scheduled wake, so PM does not have to
  reconcile multiple parallel contexts.

## `sessions_send` Between Agents

Agents can notify other agents via OpenClaw's `sessions_send`. The
gateway audits every such message into a `pm_trigger_event` /
`rt_trigger_event` asset with `wake_source=sessions_send` so the
receiving agent can account the wake in its decision record.

Hard rules (enforced by MEA / RT skills, not by the platform):

- MEA's `your_recent_impact` panel surfaces how many times MEA has
  pinged PM in the past 24 h and how many PM revisions followed.
  MEA must do a necessity check before each `sessions_send` to PM.
- Same-event ping from MEA is capped at 1 per event_id / theme — any
  continuation of the same narrative goes into the next formal `news`
  submission, not another `sessions_send`.
- High-impact events still fire `sessions_send` even when
  `your_recent_impact` is high; the harness is a mirror, not a gate.

## Reply Routing

Owner-facing messages are routed by dispatcher config in `dispatch.yaml`:

- `reply_channel`
- `reply_to`
- `reply_account_id`

The public repository keeps generic placeholders. Private deployments
override locally. Nothing in the wake path touches owner routing — it
is strictly outbound from `NotificationService`.

## Notification Types

Separated by concern in `modules/notification_service/`:

- `strategy_update` — PM produced a new revision
- `trade_event` — an execution landed
- `daily_report` — scheduled by `WorkflowOrchestratorService`
- `observe` (optional) — softer regime alerts

Trade-event messages are formatted locally before delivery so raw
execution-decision JSON never leaks to owner channels.

## Manual vs Scheduled Refresh

Both share the same dispatch path. The difference is only the trigger
source recorded on the `pm_trigger_event`:

- `wake_source=workflow_orchestrator` — Layer 2 / Layer 3 monitor
- `wake_source=sessions_send` — another agent pinged this one
- `wake_source=openclaw_cron` — direct openclaw cron fire (rare, kept
  for RT)
- manual operator action via the API → `wake_source=manual`

The receiving agent treats all of them uniformly; the audit record is
there to reconstruct "why did PM wake at 01:03 UTC" after the fact.
