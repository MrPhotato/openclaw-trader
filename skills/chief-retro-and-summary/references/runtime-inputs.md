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
- The final `POST /api/agent/submit/retro` body must use the exact same top-level `input_id` value from the pull response.
- In the owner-summary phase, the pack provides `learning_targets[]` with:
  - canonical `learning_path`
  - exact `session_key` for each agent's main session
- When Chief asks `PM / RT / MEA / Chief` to run `/self-improving-agent`, use the provided `session_key` exactly.
- In system-driven retro rounds, each participant receives:
  - a one-time compact retro pack on the first turn
  - the full transcript so far on the first turn
  - the current round index
  - the role-specific speaking instruction
- On the second turn for the same speaker, AG sends only the new transcript delta plus thin meeting state.
