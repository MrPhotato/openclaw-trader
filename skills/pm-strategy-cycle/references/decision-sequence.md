# Decision Sequence

Read in this order:

1. Current strategy and target gaps
- What is active now
- What changed since the last version
- Which scheduled rechecks are still open

2. Risk boundaries
- `policy_risk` hard limits
- Which targets are effectively constrained

3. Event layer
- `MEA` structured events
- Direct MEA reminders that could invalidate the thesis

4. Quant layer
- `QI` `1h/4h/12h`
- Use `4h/12h` as the main structure anchors
- Use `1h` as supporting context, not as a mechanical strategy trigger

5. Runtime market/account facts
- `Trade Gateway.market_data`
- Equity, exposure, positions, open order hold, current market context

Then decide:
- portfolio mode
- gross exposure band
- per-symbol direction
- `target_exposure_band_pct`
- `rt_discretion_band_pct`
- `regime-switch triggers`

`regime-switch triggers` means the specific conditions that would not just invalidate the current thesis, but justify flipping directional bias from long to short, short to long, or from active risk to flat/only_reduce.
