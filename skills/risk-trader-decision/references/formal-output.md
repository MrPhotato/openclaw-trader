# Formal Output

Before submitting, open and follow this schema exactly:
- `specs/modules/agent_gateway/contracts/execution.schema.json`

Prompt contract reference:
- `specs/modules/agent_gateway/contracts/execution.prompt.md`

Expected output shape:
- exactly one JSON object
- keep the `input_id` from your runtime pack and send it with the submit bridge call
- keep the `trigger_type` from the runtime pack's `trigger_context` when present; otherwise use a clear value such as `condition_trigger`
- output only JSON; do not emit markdown fences, prose, headings, or trailing notes
- one submission may include multi-symbol `decisions[]`
- when this round changes RT's tactical plan, or when `trigger_delta.requires_tactical_map_refresh = true`, include root-level `tactical_map_update`
- put `decisions[]` at the root level of the submission object
- do **not** wrap the batch under `execution`, `payload.execution`, `result`, or any other nested key
- if you decide to do nothing this round, submit an explicit root-level `\"decisions\": []` no-op batch only when there is no active unlocked entry gap, or when you also escalate via root-level PM recheck
- if PM has an active, unlocked target on a symbol where the desk is still unpositioned or pointed the wrong way, an all-`wait` / empty batch is invalid unless you also set root-level `pm_recheck_requested=true` with a non-empty `pm_recheck_reason`
- if `tactical_map_update` covers an active, unlocked symbol where the desk is still unpositioned or pointed the wrong way, that coin block must include a non-empty `first_entry_plan`
- actions should be chosen from:
  - `open`
  - `add`
  - `reduce`
  - `close`
  - `wait`
  - `hold`
- use `size_pct_of_exposure_budget` to express `% of exposure budget`, where exposure budget = `total_equity_usd * max_leverage`
- when you describe current exposure in `reason`, use the same `% of exposure budget` convention
- do not describe exposure using the old `% of equity` denominator
- when you have an active or newly-adjusted position, prefer leaving a short optional `reference_take_profit_condition` note for the next RT wakeup
- when you have an active or newly-adjusted position, prefer leaving a short optional `reference_stop_loss_condition` note for the next RT wakeup
- `reference_take_profit_condition` is a text memory aid only; it does not create an order and does not bypass downstream risk/execution logic
- `reference_stop_loss_condition` is also a text memory aid only; it does not create an order and does not bypass downstream risk/execution logic
- `pm_recheck_requested` and `pm_recheck_reason` are root-level escalation fields. Use them when PM's current mandate is too inconsistent or too constrained to execute responsibly right now.

RT does not approve itself.
After formal submission, risk approval happens downstream.

Bridge call for official condition-triggered, heartbeat, and PM follow-up operation:

Preferred helper:

```bash
python3 /Users/chenzian/openclaw-trader/scripts/pull_rt_runtime.py
# edit /tmp/rt_execution_submission.json in place, then submit
python3 /Users/chenzian/openclaw-trader/scripts/submit_rt_decision.py \
  --input-id "input_from_pull_pack" \
  --payload-file /tmp/rt_execution_submission.json \
  --live
```

Helper reminder:
- `/tmp/rt_execution_submission.json` must contain only the root `ExecutionSubmission` object.
- Do **not** put `input_id`, `trace_id`, `agent_role`, `task_kind`, `pm_recheck_request`, `rt_commentary`, or per-decision `execution_params` into that file.
- `submit_rt_decision.py` adds `input_id`, `live`, and optional `max_notional_usd` outside the payload file for you.

Equivalent raw HTTP call:

```bash
curl -s -X POST http://127.0.0.1:8788/api/agent/submit/execution \
  -H "Content-Type: application/json" \
  -d '{
    "input_id": "input_from_pull_pack",
    "live": true,
    "decision_id": "decision_rt_20260322_001",
    "strategy_id": "strategy_...",
    "generated_at_utc": "2026-03-22T17:57:00Z",
    "trigger_type": "condition_trigger",
    "pm_recheck_requested": false,
    "tactical_map_update": {
      "map_refresh_reason": "pm_strategy_revision",
      "portfolio_posture": "防守偏多，优先控制追价冲动。",
      "desk_focus": "BTC / ETH 只在回踩承接时推进，SOL 保持观察。",
      "risk_bias": "若 headline risk 再升级，先减风险再联系 PM。",
      "next_review_hint": "下次重点看 BTC 回踩后的承接质量和 ETH 是否重新站回结构位。",
      "coins": [
        {
          "coin": "BTC",
          "working_posture": "回踩承接优先，避免突破后追高。",
          "base_case": "只在结构确认继续的情况下慢慢推进。",
          "first_entry_plan": "如果当前仍是无仓且 BTC 保持 active long，就先用 2% exposure budget 开第一笔试探仓，不再把等待当默认动作。",
          "preferred_add_condition": "回踩 1h 结构位后重新站稳并伴随买盘恢复。",
          "preferred_reduce_condition": "若承接失败并失守最近 pullback low，则先减回观察仓。",
          "reference_take_profit_condition": "上冲 1h 范围上沿但动能衰减时，分批收一部分。",
          "reference_stop_loss_condition": "跌破关键回踩低点且卖压扩张时，优先减仓。",
          "no_trade_zone": "突破后第一根冲高延伸里不追单。",
          "force_pm_recheck_condition": "若 headline risk 继续升级并导致 BTC / ETH 同步失守关键位，要求 PM 重评。",
          "next_focus": "观察回踩后的真实承接而不是单根上冲。"
        }
      ]
    },
    "decisions": [
      {
        "symbol": "BTC",
        "action": "open",
        "direction": "long",
        "size_pct_of_exposure_budget": 2.0,
        "priority": 1,
        "urgency": "normal",
        "valid_for_minutes": 15,
        "reason": "BTC is the only active symbol, price remains inside the intended entry zone, and risk limits are clear.",
        "reference_take_profit_condition": "If BTC reaches the upper end of the 1h range and momentum stalls, trim 2% to 4% of exposure budget into strength.",
        "reference_stop_loss_condition": "If BTC loses the 1h pullback low and follow-through selling expands, reduce risk and reassess the entry thesis."
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
- do not assume a default system cap in normal production operation

Boundary reminder:
- `execution` submit is a **decision-layer** contract, not an order-layer contract.
- RT submits `decisions[]`, not `orders[]`.
- `tactical_map_update` is optional, but when present it must live at the root level beside `decisions[]`, not nested inside a decision item.
- `pm_recheck_requested` and `pm_recheck_reason` also live at the root level beside `decisions[]`.
- A payload like `{..., "execution": {"decisions": [...]}}` is invalid and will be rejected.
- An explicit empty batch `{..., "decisions": []}` is valid and means "no action this round".
- But an explicit empty batch is only valid when there is no active unlocked entry gap, or when you also escalate via `pm_recheck_requested=true` plus a concrete reason.
- When PM still has an active unlocked target and the desk has no first bite on, `wait` is not a neutral default. Either place the first bite or escalate.
- Use `hold` only to mean "keep the current position unchanged"; it is a valid no-op and should not generate a new order.
- `reference_take_profit_condition` and `reference_stop_loss_condition` are optional. Use them to leave concise textual exit clues for the next RT wakeup.
- `MARKET/LIMIT/IOC/FOK`, `order_id`, `fill_price`, `fill_size`, broker retry, and exchange margin mode are downstream concerns handled after `policy_risk` and `Trade Gateway.execution`.
- Use `live=false` only when the user explicitly asks for simulation or debugging.
