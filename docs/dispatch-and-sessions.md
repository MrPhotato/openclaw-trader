# Dispatch and Sessions

## Dispatcher Responsibilities

The dispatcher is the control plane for automated behavior. On each cycle it:

1. reloads runtime config
2. syncs news
3. evaluates market, signal, and risk state
4. decides whether to refresh strategy
5. optionally runs execution judgment
6. executes accepted plans
7. writes briefs, reports, and journals
8. sends notifications

## Action Types

The OpenClaw bridge uses a small set of action kinds:

- `strategy`
- `trade_review` (compatibility name for execution judgment)
- `event`
- `fallback`
- `daily_report`

These are not just labels for messages. They influence session targeting and notification behavior.

## OpenClaw Session Targeting

Automated agent calls do not depend on a single human-visible session name.

The dispatcher computes a synthetic `--to` target from:

- local date
- day-of-year
- action kind
- a crc32 bucket of `kind|reason`

That target is passed to:

```text
openclaw agent --agent <agent_id> --to <target> ...
```

Practical consequence:

- the system is bound to the agent id and target routing rule
- it is not fundamentally bound to `agent:crypto-chief:main`
- a visible session can change while the automated workflow still functions

## Why This Matters

Manual operator conversations often appear in a stable main session.
Automated tasks may reuse that session or may resolve to another internal target.
The reply channel back to the owner is a separate concern.

## Reply Routing

Owner-facing messages are routed by dispatcher config:

- `reply_channel`
- `reply_to`
- `reply_account_id`

The public repository keeps generic placeholders for these values.
Private deployments should override them in local runtime config.

## Notification Types

The current notification model separates concerns:

- strategy update summaries
- trade-event notifications
- optional observe notifications
- daily reports

Trade-event messages are formatted locally before delivery, which avoids leaking raw execution-decision JSON to the owner channel.

## Manual vs Automatic Refresh

Manual refreshes and automatic refreshes share much of the same machinery, but their operator expectations differ:

- manual refresh is explicit and often user-driven
- automatic refresh is schedule- or event-driven
- both can trigger follow-up execution judgment if the new strategy produces a new execution context

## Known Session Misconception

If you see work appear in a session such as `agent:crypto-chief:main`, that does not mean all future automated work is permanently tied to that session name.
It usually means the current routing resolved there or the UI chose to surface that session as the visible anchor.
