---
name: chief-retro-and-summary
description: Crypto Chief retrospective and owner-communication workflow for openclaw-trader. Use when Chief needs to judge the daily retro case, issue learning directives, and send the owner summary.
---

# Chief Retro And Summary

Use this skill for `Crypto Chief` work only.

## Use When
- Workflow Orchestrator has prepared a `retro_case` plus all required role briefs
- Owner communication
- Upgrade coordination when needed

## Job
- Pull exactly one Chief retro pack from `agent_gateway`, preferably via `scripts/pull_chief_retro.py`.
- Persist the returned pack long enough to reuse its top-level `input_id` verbatim.
- Read one `retro_case` plus three role briefs, then issue a Chief synthesis.
- If the pack says briefs are still pending, stop there. Do not synthesize, do not invent missing briefs, and do not turn this pull into a live meeting.
- Produce an owner-facing summary.
- Issue learning directives; each agent records its own learning outcome later via `/self-improving-agent`.
- Submit the retro outcome against the current `input_id`, preferably via `scripts/submit_chief_retro.py`.

## Workflow
1. Read [runtime-inputs.md](references/runtime-inputs.md) for current available material and target flow.
2. Follow [retro-flow.md](references/retro-flow.md) to read the case, inspect briefs, and write the Chief synthesis.
3. Execute [post-retro-actions.md](references/post-retro-actions.md), and carry the current `input_id` through the retro outcome submit.
4. Assume the pack was made ready by WO. Do not try to re-run prep work from the Chief session.

## Guardrails
- Default to Chinese for all non-JSON commentary unless a downstream contract explicitly requires another language.
- Do not re-create a synchronous group meeting in chat.
- If `pending_retro_brief_roles[]` is non-empty or `retro_ready_for_synthesis=false`, do not continue into synthesis. Report that retro prep is still pending.
- Do not turn daily discussion transcripts into formal truth assets.
- Learning files stay outside `memory_assets`.
- Do not write PM / RT / MEA learning files yourself.
- Do not wait for learning confirmation before sending the owner summary.
- If cross-session delivery is forbidden or fails, do not work around it by editing another agent's file yourself.
- Do not fall back to `sessions_list` or guessed session names for learning delivery. Use only the exact `learning_targets[].session_key` values provided in the Chief pack.
- If `learning_targets[]` is unexpectedly missing, state that the learning delivery metadata is missing, skip cross-session delivery, and still complete the retro submit and owner summary.
- When referring to future checks from the PM strategy, describe them as PM-authored plans.
- Do not imply a future review is already system-scheduled unless the runtime payload explicitly confirms scheduler state.
- Prefer wording like `PM scheduled next review at ...` over `next recheck at ...`.
- `POST /api/agent/submit/retro` must include the exact `input_id` plus a non-empty `owner_summary`.
- Optional retro payload fields may include `case_id`, `root_cause_ranking`, `role_judgements`, `learning_directives`, `reset_command`, and `learning_results`.
- Prefer the repo helpers:
  - `python3 /Users/chenzian/openclaw-trader/scripts/pull_chief_retro.py`
  - `python3 /Users/chenzian/openclaw-trader/scripts/submit_chief_retro.py --input-id ... --payload-file /tmp/chief_retro_submission.json`
- Do not hand-build a long escaped JSON body on the command line. Write the final submit body to a local JSON file first, then `POST` that file.
- When replying to the runtime, return exactly one JSON object only.
- `owner_summary` must be a non-empty string.
- Never invent, transform, or summarize `input_id`; reuse the exact top-level value returned by the pull bridge.

## References
- [runtime-inputs.md](references/runtime-inputs.md)
- [retro-flow.md](references/retro-flow.md)
- [post-retro-actions.md](references/post-retro-actions.md)
