---
name: pm-strategy-cycle
description: Portfolio Manager strategy review and formal strategy submission for openclaw-trader. Use when PM needs to review structured facts, refresh or revise the active strategy at UTC 01:00/13:00 or event triggers, and emit a pure JSON strategy submission.
---

# PM Strategy Cycle

Use this skill for `PM` work only.

## Use When
- Fixed strategy cycle at `UTC 01:00` or `UTC 13:00`
- `MEA` important reminder
- `policy_risk` material boundary change
- `RT` escalation
- scheduled recheck

## Job
- Pull exactly one PM runtime pack from `agent_gateway`.
- Read structured facts, not raw transcript noise.
- Decide the target portfolio state.
- Submit exactly one pure JSON `strategy` object with the current `input_id`.
- If judgment is unchanged, still submit a fresh strategy judgment.

## Workflow
1. Read [runtime-inputs.md](references/runtime-inputs.md) to see the live pull bridge, real field layout, and a working curl example.
2. Follow [decision-sequence.md](references/decision-sequence.md) in order.
3. Emit formal JSON using [formal-output.md](references/formal-output.md), and carry the current `input_id` back to the submit bridge.

## Guardrails
- Do not define execution mechanics or order tactics.
- For formal submission, emit exactly one JSON object and nothing else.
- Do not wrap formal JSON in markdown fences.
- Do not add preface, explanation, or trailing notes around formal JSON.
- Do not add `speaker_role` to a normal strategy submit. `speaker_role` is only for internal retro meeting turns.
- Do not manage memory directly.
- Do not invent system fields such as strategy id, strategy day, trigger type, or canonical timestamps.
- Prefer `MEA` structured output over raw news feeds.

## References
- [runtime-inputs.md](references/runtime-inputs.md)
- [decision-sequence.md](references/decision-sequence.md)
- [formal-output.md](references/formal-output.md)
