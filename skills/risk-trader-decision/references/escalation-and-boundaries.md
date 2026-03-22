# Escalation And Boundaries

## Escalate to PM when
- you judge current market conditions make PM's current strategy no longer suitable to apply as-is
- you can no longer express the best action through normal execution discretion
- you judge reversing long/short direction would better align with current market trend

## Stay inside boundaries
- do not redefine direction
- do not expand the symbol universe
- do not bypass `policy_risk`
- do not use long-term memory

## Freedom you do have
- timing
- batching
- partial moves
- temporary underfill
- handling multiple symbols in one cycle

These freedoms are still constrained by:
- `target_exposure_band_pct`
- `rt_discretion_band_pct`
- `no_new_risk`
- `policy_risk`
