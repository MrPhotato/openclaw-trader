# Post-Retro Actions

Execute in this order:

Precondition:
- only continue if `retro_ready_for_synthesis=true`
- if briefs are still pending, stop and report the missing roles instead of submitting a partial retro

1. Owner summary
- send a concise retro summary to the owner

2. Retro outcome submit
- submit the final retro outcome with the same `input_id` from the Chief retro pack
- the HTTP body must include:
  - the same `input_id`
  - a non-empty `owner_summary`
- strongly prefer also including:
  - `case_id`
  - `root_cause_ranking`
  - `role_judgements`
  - `learning_directives`
- optional fields:
  - `reset_command`
  - `learning_results`
- prefer editing `/tmp/chief_retro_submission.json` from `pull_chief_retro.py`, then submit with:
  - `python3 /Users/chenzian/openclaw-trader/scripts/submit_chief_retro.py --input-id "$INPUT_ID" --payload-file /tmp/chief_retro_submission.json`
- write the submit payload to a local JSON file first, then `POST` that file
- if needed, parse the top-level `input_id` directly from the saved pull response before submitting
- never fabricate a local id such as `chief-retro-...`
- if learning delivery metadata is missing, mention that explicitly in the final summary instead of falling back to guessed session routing

3. Personal learning capture
- learning directives are for downstream execution, not for synchronous confirmation
- each agent should later use `/self-improving-agent` in its own session
- do not block the retro submit on cross-session delivery
- do not write PM / RT / MEA learning yourself

Learning stays outside `memory_assets`.
