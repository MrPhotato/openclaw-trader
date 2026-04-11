# Post-Meeting Actions

Execute in this order:

1. Personal learning capture
- at meeting close, tell each agent in its own session to write personal learning via `/self-improving-agent`
  - use the exact `learning_targets[].session_key` values from the runtime pack
- do not use `sessions_list` to look for substitutes if those targets are missing or unavailable
- do not write PM / RT / MEA learning yourself
- files:
  - `.learnings/pm.md`
  - `.learnings/risk_trader.md`
  - `.learnings/macro_event_analyst.md`
  - `.learnings/crypto_chief.md`

2. Owner summary
- send a concise meeting summary to the owner

3. Retro outcome submit
- submit the final retro outcome with the same `input_id` from the Chief retro pack
- the HTTP body must include:
  - the same `input_id`
  - a non-empty `owner_summary`
- optional fields:
  - `reset_command`
  - `learning_results`
  - `transcript`
  - `round_count`
  - `meeting_id`
- prefer editing `/tmp/chief_retro_submission.json` from `pull_chief_retro.py`, then submit with:
  - `python3 /Users/chenzian/openclaw-trader/scripts/submit_chief_retro.py --input-id "$INPUT_ID" --payload-file /tmp/chief_retro_submission.json`
- write the submit payload to a local JSON file first, then `POST` that file
- if needed, parse the top-level `input_id` directly from the saved pull response before submitting
- never fabricate a local id such as `chief-retro-...`
- if learning delivery metadata is missing, mention that explicitly in the final summary instead of falling back to guessed session routing

Learning stays outside `memory_assets`.
