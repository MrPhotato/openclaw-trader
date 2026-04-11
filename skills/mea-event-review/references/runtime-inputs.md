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

`MEA -> AG submit bridge (+ input_id) -> news.schema.json validation -> memory_assets`

High-importance reminders remain direct communication to `PM` and `RT`.

## Use Now
- Pull once, work from that pack, and submit against the same `input_id`.
- Use `market` only to help judge event relevance, not to replace structured event reasoning.
- Before waking `PM`, compare the new event against:
  - the latest `PM` strategy in the pack,
  - the latest visible `PM` trigger context,
  - and the recent direct reminder you already sent on the same theme.
- Only wake `PM` when the state changed. If the theme, direction, and action implication are unchanged, do not send another `PM` trigger.
- Repeated same-theme updates should usually flow into the normal `news` submission, not a new `sessions_send` interrupt to `PM`.
