---
name: mea-event-review
description: Macro Event Analyst workflow for openclaw-trader. Use when MEA needs to review news batches, optionally search the web via /gemini, produce structured news JSON, and directly notify PM and RT about high-importance events.
---

# MEA Event Review

Use this skill for `MEA` work only.

## Use When
- Every `2` hours
- Immediate trigger on `NEWS_BATCH_READY`

## Job
- Pull exactly one MEA runtime pack from `agent_gateway`.
- Review incoming news batches.
- Resolve important uncertainties with `/gemini` only when needed.
- Produce exactly one pure JSON `news` submission when making a formal submit.
- Submit against the current `input_id`.
- Only author `events`; the system will add `submission_id` and `generated_at_utc`.
- Directly notify `PM` and `RT` when importance is `high`.

## Workflow
1. Read [runtime-inputs.md](references/runtime-inputs.md).
2. Follow [search-playbook.md](references/search-playbook.md) when a batch is ambiguous or high impact.
3. Emit formal JSON using [formal-output.md](references/formal-output.md), and carry the current `input_id` back to the submit bridge.

## Guardrails
- Default to Chinese for all non-JSON commentary unless a downstream contract explicitly requires another language.
- Do not hold strategy authority.
- Do not wait for WO to track high-priority events.
- Formal `news` submission must be JSON only, with no markdown fence or prose wrapper.
- Do not store personal memory in `memory_assets`.

## References
- [runtime-inputs.md](references/runtime-inputs.md)
- [search-playbook.md](references/search-playbook.md)
- [formal-output.md](references/formal-output.md)
