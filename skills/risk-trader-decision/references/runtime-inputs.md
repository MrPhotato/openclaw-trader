# Runtime Inputs

## Current implementation
Current runtime path is:

`OpenClaw cron or event wakeup -> RT -> AG pull bridge -> single RT runtime pack`

RT should pull one `rt` runtime pack from `agent_gateway`, then read:
- `market`
- `execution_contexts`
- `strategy`
- `risk_limits`
- `forecasts`
- `news_events`
- `recent_execution_thoughts`
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
- when present, each recent thought may also carry `reference_take_profit_condition`, a textual exit clue left by RT for the next cadence
- Real-time `captured_at` timestamps
- Normalized exposure/share fields that already follow the new house convention:
  - `% of exposure budget`
  - `exposure budget = total_equity_usd * max_leverage`

## Exposure math

Use the runtime pack's normalized exposure/share values first.

Current house convention:

- `size_pct_of_equity`
- `position_share_pct_of_equity`
- `current_position_share_pct`

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
  -d '{"trigger_type":"cadence","params":{"cadence_source":"openclaw_cron","cadence_label":"rt_10m"}}'
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
- Treat `execution_contexts` as the actionable bridge from PM formal strategy to RT execution batching.
- Use `news_events` as a thin headline-risk layer, not as a substitute for PM or MEA analysis.
- Use `recent_execution_thoughts` to remember what you recently tried, why you tried it, what actually filled, and what reference take-profit condition you previously left for yourself.
- When reasoning about exposure, quote the normalized share from the runtime pack instead of recomputing it from raw notional and equity.
- For official cadence and PM follow-up operation, submit with `live=true`.
- Only pass `max_notional_usd` when the user or upstream trigger explicitly asks for a temporary execution cap.
