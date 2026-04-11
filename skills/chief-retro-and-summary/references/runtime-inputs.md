# Runtime Inputs

## Current implementation
Current runtime path is:

`OpenClaw cron or event wakeup -> Chief -> AG pull bridge -> single chief-retro pack`

Chief should pull one `chief-retro` pack from `agent_gateway`, then read:
- `retro_pack`
- `trigger_context`
- lease metadata:
  - `input_id`
  - `trace_id`
  - `expires_at_utc`

Operational rule:
- Treat the returned top-level `input_id` as an opaque lease token.
- Save it locally if needed, but do not rename it, rebuild it, or replace it with a human-readable placeholder.

Source of truth in code:
- `src/openclaw_trader/modules/agent_gateway/service.py`
- `src/openclaw_trader/app/api.py`

## Target contract
Chief should run retrospectives against a shared daily pack centered on:
- `Trade Gateway` market and execution timeline
- key `QI` snapshots
- key `policy_risk` changes
- PM strategy versions
- RT execution batches
- MEA high-impact events
- the live retro transcript that AG is driving across 2 rounds

## Use Now
- Pull once, work from that pack, and submit against the same `input_id`.
- Prefer:
  - `python3 /Users/chenzian/openclaw-trader/scripts/pull_chief_retro.py`
  - This writes:
    - `/tmp/chief_retro_pack.json`
    - `/tmp/chief_retro_submission.json`
- The final `POST /api/agent/submit/retro` body must use the exact same top-level `input_id` value from the pull response.
- The submit body must include:
  - `input_id`
  - `owner_summary`
- Optional fields:
  - `reset_command`
  - `learning_results`
  - `transcript`
  - `round_count`
  - `meeting_id`
- Prefer:
  - `python3 /Users/chenzian/openclaw-trader/scripts/submit_chief_retro.py --input-id "$INPUT_ID" --payload-file /tmp/chief_retro_submission.json`
- Do not hand-escape a long JSON body inline. Write a JSON file first, then `POST` that file.
- In the owner-summary phase, the pack provides `learning_targets[]` with:
  - canonical `learning_path`
  - exact `session_key` for each agent's main session
- Use only those `learning_targets[].session_key` values for learning delivery.
- Do not call `sessions_list` to discover or guess alternative session names.
- If `learning_targets[]` is unexpectedly absent, note the missing metadata in the retro narrative and continue without waiting for learning confirmation.
- When Chief asks `PM / RT / MEA / Chief` to run `/self-improving-agent`, use the provided `session_key` exactly.
- In system-driven retro rounds, each participant receives:
  - a one-time compact retro pack on the first turn
  - the full transcript so far on the first turn
  - the current round index
  - the role-specific speaking instruction
- On the second turn for the same speaker, AG sends only the new transcript delta plus thin meeting state.
