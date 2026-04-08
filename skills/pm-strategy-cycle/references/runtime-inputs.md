# Runtime Inputs

## Current implementation
Current runtime path is:

`OpenClaw cron or event wakeup -> PM -> AG pull bridge -> single PM runtime pack`

PM should pull one `pm` runtime pack from `agent_gateway`.

Working example:

```bash
curl -s -X POST http://127.0.0.1:8788/api/agent/pull/pm \
  -H "Content-Type: application/json" \
  -d '{"trigger_type":"manual","params":{}}' \
  > /tmp/pm_runtime_pack.json
```

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
  "trigger_type": "manual",
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
- `latest_risk_brake_event` may be present when the system just forced a reduce or exit order before waking PM
- `previous_strategy` already uses canonical strategy field names such as:
  - `portfolio_thesis`
  - `portfolio_invalidation`
  - `change_summary`
- do not assume older aliases such as `thesis` or `invalidation`

Source of truth in code:
- `src/openclaw_trader/modules/agent_gateway/service.py`
- `src/openclaw_trader/app/api.py`

## Target contract
PM should keep working from structured facts, but the formal output path is:

`PM -> AG submit bridge (+ input_id) -> strategy.schema.json validation -> MQ -> memory_assets + workflow_orchestrator`

PM should not assume it can request data directly from MQ.

## Use Now
- Pull once, work from that pack, and submit against the same `input_id`.
- Do not probe the bridge with `GET /api/agent/pull/pm`. The live bridge is `POST` only.
- Never use `web_fetch` for `127.0.0.1` or localhost. Use shell `curl` only.
- Do not infer `input_id` from timestamps, process ids, filenames, or partial logs. Read the top-level `input_id` from the runtime pack directly.
- Because runtime pack output can be long, prefer writing it to a file first and then reading the file. Do not trust truncated process output.
- Do not paste the full runtime pack back into the conversation after pulling it. Keep the large JSON in a file and only extract the fields you need.
- If `latest_risk_brake_event` is present, treat it as a hard desk fact: the system has already reduced or exited risk. Your job is to re-evaluate mandate and publish a new strategy revision around that new state.
- If submit fails with `unknown_input_id`, do one fresh `pull/pm`, replace the old `input_id`, and retry once. Stop there; repeated retries with guessed ids are always wrong.
- If runtime facts and later design notes diverge, follow the live pack plus the formal strategy contract.
- Do not wait for `workflow_orchestrator` to push a strategy payload. PM is agent-first now.
