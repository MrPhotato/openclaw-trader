# Runtime Inputs

## Current implementation
Current runtime path is:

`OpenClaw cron or event wakeup -> MEA -> AG pull bridge -> single MEA runtime pack`

MEA should pull one `mea` runtime pack from `agent_gateway`, then read:
- `news_events`
- `market`
- `macro_memory`
- `trigger_context`
- lease metadata:
  - `input_id`
  - `trace_id`
  - `expires_at_utc`

Source of truth in code:
- `src/openclaw_trader/modules/agent_gateway/service.py`
- `src/openclaw_trader/app/api.py`

## Target contract
Target formal chain remains simple:

`MEA -> AG submit bridge (+ input_id) -> news.schema.json validation -> MQ -> memory_assets`

High-importance reminders remain direct communication to `PM` and `RT`.

## Use Now
- Pull once, work from that pack, and submit against the same `input_id`.
- Use `market` only to help judge event relevance, not to replace structured event reasoning.
