# Runtime Inputs

## Current implementation
Current runtime path is:

`Workflow Orchestrator condition trigger or heartbeat -> OpenClaw cron run -> RT -> AG pull bridge -> single RT runtime pack`

RT should pull one `rt` runtime pack from `agent_gateway`, then read:
- `rt_decision_digest` first
- `market`
- `execution_contexts`
- `strategy`
- `risk_limits`
- `forecasts`
- `news_events`
- `recent_execution_thoughts`
- `latest_rt_trigger_event` when RT was awakened by Workflow Orchestrator
- `latest_risk_brake_event` when the system itself just executed a forced risk order
- `trigger_context`
- lease metadata:
  - `input_id`
  - `trace_id`
  - `expires_at_utc`

## Account State Source of Truth

**Always use `/api/agent/pull/rt` to get account state.**

Do NOT use `otrader portfolio` or any other CLI command to query account/positions.
The `otrader portfolio` command has caching issues and may return stale data (observed lag of 2+ hours).

The runtime pack from `/api/agent/pull/rt` contains:
- `market.accounts` - per-coin account snapshots
- `market.portfolio` - portfolio-level summary with positions array
- `news_events` - a thin, trade-oriented recent news layer for headline risk
- `recent_execution_thoughts` - the last 5 RT decision summaries paired with actual execution outcome details
- `latest_rt_trigger_event` - the latest objective trigger record, if WO called the registered RT cron job because PM strategy changed, MEA raised a high-impact event, exposure drifted, execution filled, market structure changed, or heartbeat elapsed
- `latest_risk_brake_event` - the latest system risk-brake record, if the system already forced a reduce or exit order before waking RT
- `rt_decision_digest` - a compact, decision-first summary that already merges trigger reason, portfolio snapshot, strategy snapshot, symbol focus, recent thoughts, and thin headline risk
- when present, each recent thought may also carry `reference_take_profit_condition` and `reference_stop_loss_condition`, textual exit clues left by RT for the next wakeup
- Real-time `captured_at` timestamps
- Normalized exposure/share fields that already follow the new house convention:
  - `% of exposure budget`
  - `exposure budget = total_equity_usd * max_leverage`

## Exposure math

Use the runtime pack's normalized exposure/share values first.

Current house convention:

- `size_pct_of_exposure_budget`
- `position_share_pct_of_exposure_budget`
- `current_position_share_pct_of_exposure_budget`

all mean:

`notional_usd / (total_equity_usd * max_leverage) * 100`

They do **not** mean:

`notional_usd / total_equity_usd * 100`

Example:

- `total_equity_usd = 982.13`
- `max_leverage = 5`
- `current_notional_usd = 233.67`

Then:

- correct normalized exposure share = `233.67 / (982.13 * 5) * 100 ≈ 4.76%`
- old wrong equity-only share = `233.67 / 982.13 * 100 ≈ 23.8%`

Never use the second number for RT decisioning in this system.

This is the only reliable source for current positions, equity, and exposure.

Working example:

```bash
curl -s -X POST http://127.0.0.1:8788/api/agent/pull/rt \
  -H "Content-Type: application/json" \
  -d '{"trigger_type":"condition_trigger","params":{"source":"workflow_orchestrator","runner":"openclaw_cron_run"}}' \
  > /tmp/rt_runtime_pack.json

python3 - <<'PY'
import json
from pathlib import Path

pack = json.loads(Path("/tmp/rt_runtime_pack.json").read_text())
print(pack["input_id"])
print(json.dumps(pack["payload"]["rt_decision_digest"], ensure_ascii=False, indent=2))
PY
```

Source of truth in code:
- `src/openclaw_trader/modules/agent_gateway/service.py`
- `src/openclaw_trader/app/api.py`

## Target contract
Target formal chain is:

`RT -> AG submit bridge (+ input_id) -> MQ -> policy_risk -> MQ -> Trade Gateway.execution`

RT remains a decision agent, not a market-data requester.
RT also remains a decision agent, not an order router.

## Use Now
- Pull once, work from that pack, and submit against the same `input_id`.
- Prefer writing the runtime pack to a file first and then reading the needed fields from that file. Do not dump the full JSON pack back into the model context.
- Read `rt_decision_digest` first. It is the default working view for this round.
- Only drill into raw `execution_contexts`, `market.market_context`, `recent_execution_thoughts`, or `news_events` if the digest leaves a material ambiguity.
- Do not use `GET /api/agent/pull/rt`. The live bridge is `POST` only.
- Treat `execution_contexts` as the actionable bridge from PM formal strategy to RT execution batching.
- Use `news_events` as a thin headline-risk layer only when the digest indicates they matter.
- Use `recent_execution_thoughts` only when the digest indicates you need historical self-checking or when the last few actions are directly relevant to this trigger.
- If `latest_rt_trigger_event` is present, read it first as the reason you were awakened. It is trigger context, not trading authorization; the actual action still must respect PM mandate and `policy_risk`.
- If `latest_risk_brake_event` is present, read it before planning any action. It means the system has already reduced or exited risk on your behalf; treat that as an accomplished fact, not a suggestion.
- Never use any identifier inside `latest_rt_trigger_event` as the submit `input_id`. The only valid submit `input_id` is the top-level `input_id` returned by `/api/agent/pull/rt`.
- Never use any identifier inside `latest_risk_brake_event` as the submit `input_id`. The only valid submit `input_id` is the top-level `input_id` returned by `/api/agent/pull/rt`.
- Use the runtime pack's top-level `trigger_context.trigger_type` for the formal `trigger_type` when present. Do not derive formal submit fields from `latest_rt_trigger_event` ids.
- If `latest_risk_brake_event.lock_mode` is `reduce_only`, you may only `reduce / close / hold / wait`.
- If `latest_risk_brake_event.lock_mode` is `flat_only`, you may only `close / hold / wait`.
- When reasoning about exposure, quote the normalized share from the runtime pack instead of recomputing it from raw notional and equity.
- For official condition-triggered, heartbeat, and PM follow-up operation, submit with `live=true`.
- Only pass `max_notional_usd` when the user or upstream trigger explicitly asks for a temporary execution cap.
