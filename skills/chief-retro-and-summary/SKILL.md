---
name: chief-retro-and-summary
description: Crypto Chief retrospective and owner-communication workflow for openclaw-trader. Use when Chief needs to host the daily internal roundtable, ask each agent to record post-meeting learning, and send the owner summary.
---

# Chief Retro And Summary

Use this skill for `Crypto Chief` work only.

## Use When
- Daily retrospective around `UTC 23:00`
- Owner communication
- Upgrade coordination when needed

## Job
- Pull exactly one Chief retro pack from `agent_gateway`.
- Persist the returned pack long enough to reuse its top-level `input_id` verbatim.
- Host the daily retrospective as a structured internal roundtable.
- Keep discussion structured and blameless.
- Produce an owner-facing summary.
- Ensure each agent records its own learning outcome.
- Submit the retro outcome against the current `input_id`.

## Workflow
1. Read [runtime-inputs.md](references/runtime-inputs.md) for current available material and target flow.
2. Follow [retro-flow.md](references/retro-flow.md) to run the meeting.
3. Execute [post-meeting-actions.md](references/post-meeting-actions.md), and carry the current `input_id` through the retro outcome submit.

## Guardrails
- No rigid meeting template is required.
- Do not turn daily discussion transcripts into formal truth assets.
- Run a maximum of 2 rounds.
- Every round must follow `PM -> RT -> MEA -> Chief`.
- Every participant must speak exactly once per round.
- Learning files stay outside `memory_assets`.
- Do not write PM / RT / MEA learning files yourself.
- Do not wait for learning confirmation before sending the owner summary.
- If cross-session delivery is forbidden or fails, do not work around it by editing another agent's file yourself.
- When referring to future checks from the PM strategy, describe them as PM-authored plans.
- Do not imply a future review is already system-scheduled unless the runtime payload explicitly confirms scheduler state.
- Prefer wording like `PM scheduled next review at ...` over `next recheck at ...`.
- When replying to the runtime, return exactly one JSON object only.
- `owner_summary` must be a non-empty string.
- Never invent, transform, or summarize `input_id`; reuse the exact top-level value returned by the pull bridge.

## References
- [runtime-inputs.md](references/runtime-inputs.md)
- [retro-flow.md](references/retro-flow.md)
- [post-meeting-actions.md](references/post-meeting-actions.md)
