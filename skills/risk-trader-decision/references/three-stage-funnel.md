# Three-Stage Funnel

# Default read order
Before the funnel, read in this order:
- `trigger_delta`
- `standing_tactical_map`
- `rt_decision_digest`
- helper-generated `/tmp/rt_execution_submission.json`

Only drill into raw sections when the digest leaves ambiguity:
- `execution_contexts`
- `market.market_context`
- `recent_execution_thoughts`
- `news_events`

## 1. Task eligibility
Read first:
- `trigger_delta`
- `standing_tactical_map`
- `rt_decision_digest.trigger_summary`
- `rt_decision_digest.portfolio_summary`
- `rt_decision_digest.strategy_summary`
- current target and target gap
- `target_exposure_band_pct`
- `rt_discretion_band_pct`
- `policy_risk`
- current positions and account state

Answer:
- can I act now
- do I need to act now
- do I need to refresh the tactical map in this same round
- which parts of the submission scaffold need to be filled rather than rebuilt
- if PM has an active unlocked entry gap, do I enter now or explicitly escalate with `pm_recheck_requested`

## 2. Market timing
Read second:
- `rt_decision_digest.focus_symbols`
- `QI` `1h/4h/12h`
- compressed price series
- key levels
- breakout/retest state
- volatility state
- shape summary

Answer:
- is now a good time to act
- should I chase, wait, reduce, or only partially move

## 3. Execution landing
Read last:
- `rt_decision_digest.recent_memory`
- best bid/ask
- spread
- depth
- open orders
- recent fills and failures
- product constraints

Answer:
- how to act now
- how many symbols to handle in this batch
- whether to `open / add / reduce / close / wait`
