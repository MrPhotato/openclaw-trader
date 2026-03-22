# Post-Meeting Actions

Execute in this order:

1. Personal learning capture
- at meeting close, tell each agent in its own session to write personal learning via `/self-improving-agent`
  - use the exact `learning_targets[].session_key` values from the runtime pack
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
- if needed, parse the top-level `input_id` directly from the saved pull response before submitting
- never fabricate a local id such as `chief-retro-...`

Learning stays outside `memory_assets`.
