# Formal Output

Before submitting, open and follow this schema exactly:
- `specs/modules/agent_gateway/contracts/execution.schema.json`

Prompt contract reference:
- `specs/modules/agent_gateway/contracts/execution.prompt.md`

Expected output shape:
- exactly one JSON object
- keep the `input_id` from your runtime pack and send it with the submit bridge call
- output only JSON; do not emit markdown fences, prose, headings, or trailing notes
- one submission may include multi-symbol `decisions[]`
- put `decisions[]` at the root level of the submission object
- do **not** wrap the batch under `execution`, `payload.execution`, `result`, or any other nested key
- if you decide to do nothing this round, submit an explicit root-level `\"decisions\": []` no-op batch
- actions should be chosen from:
  - `open`
  - `add`
  - `reduce`
  - `close`
  - `wait`
  - `hold`
- treat `size_pct_of_equity` as `% of exposure budget`, where exposure budget = `total_equity_usd * max_leverage`
- when you describe current exposure in `reason`, use the same `% of exposure budget` convention
- do not describe exposure using the old `% of equity` denominator
- when you have an active or newly-adjusted position, prefer leaving a short optional `reference_take_profit_condition` note for the next cadence
- `reference_take_profit_condition` is a text memory aid only; it does not create an order and does not bypass downstream risk/execution logic

RT does not approve itself.
After formal submission, risk approval happens downstream.

Bridge call for official cadence and PM follow-up:

```bash
curl -s -X POST http://127.0.0.1:8788/api/agent/submit/execution \
  -H "Content-Type: application/json" \
  -d '{
    "input_id": "input_from_pull_pack",
    "live": true,
    "decision_id": "decision_rt_20260322_001",
    "strategy_id": "strategy_...",
    "generated_at_utc": "2026-03-22T17:57:00Z",
    "trigger_type": "cadence",
    "decisions": [
      {
        "symbol": "BTC",
        "action": "open",
        "direction": "long",
        "size_pct_of_equity": 2.0,
        "priority": 1,
        "urgency": "normal",
        "valid_for_minutes": 15,
        "reason": "BTC is the only active symbol, price remains inside the intended entry zone, and risk limits are clear.",
        "reference_take_profit_condition": "If BTC reaches the upper end of the 1h range and momentum stalls, trim 2% to 4% of exposure budget into strength."
      },
      {
        "symbol": "ETH",
        "action": "wait",
        "priority": 2,
        "urgency": "low",
        "valid_for_minutes": 15,
        "reason": "ETH remains on watch and there is no higher-quality tactical action this round."
      }
    ]
  }'
```

Optional testing/debug override:
- include `max_notional_usd` only when the user or upstream trigger explicitly requests a temporary cap
- do not assume a default system cap in normal production cadence

Boundary reminder:
- `execution` submit is a **decision-layer** contract, not an order-layer contract.
- RT submits `decisions[]`, not `orders[]`.
- A payload like `{..., "execution": {"decisions": [...]}}` is invalid and will be rejected.
- An explicit empty batch `{..., "decisions": []}` is valid and means "no action this round".
- Use `hold` only to mean "keep the current position unchanged"; it is a valid no-op and should not generate a new order.
- `reference_take_profit_condition` is optional. Use it to leave a concise textual exit clue for the next 15-minute wakeup.
- `MARKET/LIMIT/IOC/FOK`, `order_id`, `fill_price`, `fill_size`, broker retry, and exchange margin mode are downstream concerns handled after `policy_risk` and `Trade Gateway.execution`.
- Use `live=false` only when the user explicitly asks for simulation or debugging.
