# Runtime Inputs

## Current implementation
Current runtime path is:

`OpenClaw cron or event wakeup -> PM -> AG pull bridge -> single PM runtime pack`

PM should pull one `pm` runtime pack from `agent_gateway`.

Working example:

```bash
curl -s -X POST http://127.0.0.1:8788/api/agent/pull/pm \
  -H "Content-Type: application/json" \
  -d '{"trigger_type":"manual","params":{}}'
```

This call is not instant. In the live stack it can take roughly `20-30s` because the bridge compiles market, news, forecast, and risk facts before returning.

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
- If runtime facts and later design notes diverge, follow the live pack plus the formal strategy contract.
- Do not wait for `workflow_orchestrator` to push a strategy payload. PM is agent-first now.
