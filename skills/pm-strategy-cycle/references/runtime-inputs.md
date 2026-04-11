# Runtime Inputs

## Current implementation
Current runtime path is:

`OpenClaw cron or event wakeup -> PM -> AG pull bridge -> single PM runtime pack`

PM should pull one `pm` runtime pack from `agent_gateway`.

Fixed `pm-main` cadence example:

```bash
python3 /Users/chenzian/openclaw-trader/scripts/pull_pm_runtime.py \
  --trigger-type pm_main_cron \
  --wake-source openclaw_cron \
  --output /tmp/pm_runtime_pack.json
```

Direct message wake example:

```bash
python3 /Users/chenzian/openclaw-trader/scripts/pull_pm_runtime.py \
  --trigger-type agent_message \
  --wake-source sessions_send \
  --source-role macro_event_analyst \
  --reason "high-impact macro alert" \
  --severity high \
  --output /tmp/pm_runtime_pack.json
```

Use `manual` only for a true ad-hoc manual refresh. If a pending system wake such as `scheduled_recheck` or `risk_brake` already exists, let the bridge preserve that trigger instead of overwriting it.

This call is not instant. In the live stack it can take roughly `20-30s` because the bridge compiles market, news, forecast, and risk facts before returning.

Recommended extraction pattern:

```bash
python3 - <<'PY'
import json
from pathlib import Path

pack = json.loads(Path("/tmp/pm_runtime_pack.json").read_text())
print(pack["input_id"])
PY
```

The response shape is:

```json
{
  "agent_role": "pm",
  "task_kind": "strategy",
  "input_id": "input_...",
  "trace_id": "trace_...",
  "trigger_type": "pm_main_cron",
  "expires_at_utc": "2026-03-22T...",
  "payload": {
    "trace_id": "trace_...",
    "market": {
      "market": {},
      "market_context": {},
      "portfolio": {},
      "accounts": [],
      "execution_history": [],
      "product_metadata": []
    },
    "risk_limits": {},
    "forecasts": {},
    "news_events": [],
    "previous_strategy": {},
    "macro_memory": [],
    "trigger_context": {}
  }
}
```

Important live field layout:
- lease metadata lives at the top level:
  - `input_id`
  - `trace_id`
  - `expires_at_utc`
  - `trigger_type`
- strategy facts live under `payload`
- `market_context` and `portfolio` are **inside** `payload.market`, not top-level siblings
- `news_events` is a compact recent-news layer for PM review, not an unbounded raw news dump
- `latest_pm_trigger_event` records the audited PM wake reason for this run. Fixed cadence, workflow wakes, direct agent messages, and manual refreshes should all land here.
- `latest_risk_brake_event` may be present when the system just forced a reduce or exit order before waking PM
- `risk_brake_policy` describes the standing desk rule: the system watches both single-position peak drawdown and portfolio peak drawdown, and it can automatically reduce or exit before PM wakes
- `previous_strategy` already uses canonical strategy field names such as:
  - `portfolio_thesis`
  - `portfolio_invalidation`
  - `flip_triggers`
  - `change_summary`
- do not assume older aliases such as `thesis` or `invalidation`

Source of truth in code:
- `src/openclaw_trader/modules/agent_gateway/service.py`
- `src/openclaw_trader/app/api.py`

## Target contract
PM should keep working from structured facts, but the formal output path is:

`PM -> AG submit bridge (+ input_id) -> strategy.schema.json validation -> memory_assets + workflow_orchestrator`

PM should not assume it can request data directly from any message broker.

## Use Now
- Pull once, work from that pack, and submit against the same `input_id`.
- Do not probe the bridge with `GET /api/agent/pull/pm`. The live bridge is `POST` only.
- Never use `web_fetch` for `127.0.0.1` or localhost. Use shell `curl` only.
- Prefer `python3 /Users/chenzian/openclaw-trader/scripts/pull_pm_runtime.py` over handwritten curl so PM wake provenance stays audited and consistent.
- The bridge now has a narrow safety net for raw `pull/pm`: if PM was just woken by a recent direct agent message and then issues a bare `pm_unspecified` pull, the service will inherit that recent message provenance instead of silently downgrading to `pm_unspecified`. This is only a guardrail, not the preferred path.
- Do not infer `input_id` from timestamps, process ids, filenames, or partial logs. Read the top-level `input_id` from the runtime pack directly.
- Because runtime pack output can be long, prefer writing it to a file first and then reading the file. Do not trust truncated process output.
- Do not paste the full runtime pack back into the conversation after pulling it. Keep the large JSON in a file and only extract the fields you need.
- If `latest_risk_brake_event` is present, treat it as a hard desk fact: the system has already reduced or exited risk. Your job is to re-evaluate mandate and publish a new strategy revision around that new state.
- Treat `risk_brake_policy` as a standing house rule, not a suggestion. PM is not the only risk controller now: the system can auto-reduce or auto-exit on both single-position peak drawdown and portfolio peak drawdown, then wake PM to revise mandate.
- If you were woken by RT / MEA / Chief / owner directly, classify the wake as `agent_message` and include `source_role`, `wake_source=sessions_send`, and a one-line `reason` in the pull helper args.
- If submit fails with `unknown_input_id`, do one fresh `pull/pm`, replace the old `input_id`, and retry once. Stop there; repeated retries with guessed ids are always wrong.
- If runtime facts and later design notes diverge, follow the live pack plus the formal strategy contract.
- Do not wait for `workflow_orchestrator` to push a strategy payload. PM is agent-first now.
