# Formal Output

Before submitting, open and follow this schema exactly:
- `specs/modules/agent_gateway/contracts/strategy.schema.json`

Prompt contract reference:
- `specs/modules/agent_gateway/contracts/strategy.prompt.md`

Important fields to always think about:
- `portfolio_mode`
- `target_gross_exposure_band_pct`
- `portfolio_thesis`
- `portfolio_invalidation`
- `change_summary`
- `targets[]`
- `target_exposure_band_pct`
- `rt_discretion_band_pct`
- `scheduled_rechecks[]`

Rules:
- Formal submission is exactly one JSON object.
- Keep the `input_id` from your runtime pack and send it with the submit bridge call.
- Output only JSON. Do not emit markdown fences, commentary, bullets, headings, or trailing text.
- If you need to think or explain, do it before the formal submit step, not inside the submission itself.
- If judgment is unchanged, still emit a fresh strategy submission.
- Do not add execution tactics such as order type, order count, or entry path.
- Treat all exposure percentages as `% of exposure budget`, where exposure budget = `total_equity_usd * max_leverage`.
- Do not emit `strategy_id`, `strategy_day_utc`, `generated_at_utc`, `trigger_type`, or any source-ref fields. The system will add those later.
- Do not add `speaker_role` to a normal strategy submit.

Submit bridge:

```bash
curl -s -X POST http://127.0.0.1:8788/api/agent/submit/strategy \
  -H "Content-Type: application/json" \
  -d '{
    "input_id": "input_from_pull_pack",
    "portfolio_mode": "defensive",
    "target_gross_exposure_band_pct": [0, 15],
    "portfolio_thesis": "Range-bound market with weak follow-through. Keep BTC active, keep ETH and SOL on watch, and stay defensive until 4h trend confirms.",
    "portfolio_invalidation": "A clean 4h breakout with strong confirmation, or a policy/risk boundary change that invalidates the defensive stance.",
    "change_summary": "Kept defensive posture and narrowed active risk to BTC while leaving ETH and SOL on watch.",
    "targets": [
      {
        "symbol": "BTC",
        "state": "active",
        "direction": "long",
        "target_exposure_band_pct": [0, 10],
        "rt_discretion_band_pct": 5,
        "priority": 1
      },
      {
        "symbol": "ETH",
        "state": "watch",
        "direction": "flat",
        "target_exposure_band_pct": [0, 5],
        "rt_discretion_band_pct": 5,
        "priority": 2
      }
    ],
    "scheduled_rechecks": [
      {
        "recheck_at_utc": "2026-03-22T09:00:00Z",
        "scope": "portfolio",
        "reason": "Re-evaluate after the next major intraday structure update."
      }
    ]
  }'
```

API compatibility note:
- `submit/strategy` accepts both:
  - flat submit: `{"input_id":"...","portfolio_mode":"...","..."}`
  - wrapped submit: `{"input_id":"...","payload":{...strategy fields...}}`
- flat submit is preferred because it is simpler and easier to reason about.

Common mapping reminders:
- `portfolio_thesis`, not `thesis`
- `portfolio_invalidation`, not `invalidation`
- `change_summary`, not `summary`
- `input_id` must be carried back exactly as issued by the pull bridge
