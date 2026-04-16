# Strategy and Risk

## Mental Model

The strategy layer produces a target exposure, not a blind market order.

The runtime then asks:

- what side should the position be on
- how large should the target position be
- what single-order size is allowed
- whether current risk state or fresh news blocks the change

`market-intelligence` now sits inside that first half of the decision. It can still produce a directional view, but it also decides whether the trade is worth taking after costs and which calibrated execution policy should gate the signal.

It now does that across three fixed horizons:

- `12h` sets directional bias
- `4h` confirms or opposes that bias
- `1h` decides trigger timing

The runtime and `crypto-chief` no longer treat `1h` as the only decision-maker.

## Position Terms

### Target position share

The recommended end-state exposure as a share of the exposure budget.

### Order share

The maximum size a single opening or adding action should take toward the target.

### Margin vs notional

The strategy and most repository defaults are specified in exposure-budget share terms.
The runtime converts margin-sized targets into notional using leverage.

## Signal Contexts

### `true_flat`

- very high confidence the market is actually flat
- default target is `0%`

### `breakout_watch`

- still flat, but direction probabilities are leaning one way
- default target is still `0%`
- used as a watch state, not a direct entry signal

### `direction_pending`

- still flat, but direction evidence is incomplete
- default target is `0%`

### `directional_weak`

- side is not flat
- confidence is below the medium threshold
- default range: `15%-25%`
- default order share: `15%`

### `directional_medium`

- side is not flat
- confidence is at or above the weak threshold but below strong
- default range: `30%-50%`
- default order share: `25%`

### `directional_strong`

- side is not flat
- confidence is at or above the strong threshold
- default range: `50%-70%`
- default order share: `35%`

## Risk Stages

Risk stage can cap the strategy even if the directional signal is strong.

### `normal`

- no extra cap beyond the directional range

### `observe`

- current position is under drawdown attention
- target range is capped to `0%-15%`
- order share is capped to `15%`

### `reduce`

- current position should shrink further
- target range is capped to `0%-4%`
- order share is capped to `4%`

### `exit`

- position should be fully exited
- target becomes `0%`

Default drawdown thresholds come from `risk.yaml`:

- observe at `4%`
- reduce at `7%`
- exit at `10%`

## Funding and News Gates

### Funding hot scaling

If funding is above the configured threshold, the strategy scales position and order sizes down.

### Event action layer

Fresh news is no longer treated as one flat freeze rule.

The runtime now converts structured news into an event-action summary that can:

- downgrade `standard` to `probe`
- block new entry
- block add
- block flip
- force trim/exit only

Current action states are:

- `normal`
- `caution`
- `freeze`
- `reduce_only`

The intent is:

- scheduled macro and high-risk event windows can temporarily block new risk
- exchange-status incidents can go all the way to `reduce_only`
- dynamic headline shocks can downgrade sizing without taking over direction
- `caution` can block add/flip while still allowing a meaningful `probe`

The repository default freshness window is still `15` minutes, but event handling now has a richer action mask than a single observe gate.

## Market-Intelligence Execution Policy

The public runtime defaults in `model.yaml` still matter, but they are now only the starting point.

During training, `market-intelligence` can calibrate:

- minimum confidence
- minimum long/short probability
- minimum trade-quality probability
- order-size floor ratio
- order-size ceiling ratio

Prediction then resolves the calibrated policy for the current regime and can suppress a directional signal back to `flat` if any threshold is not met.

This means two runs with the same hard risk config can still behave differently if the trained model artifacts and calibration bundle differ.

## Multi-Horizon Runtime Policy

The live runtime now reads a structured policy result on top of the raw signal:

- `bias`
- `confirmation`
- `trigger`
- `size_tier`
- `allowed_actions`
- `event_action`

Current roles are:

- `12h` -> bias
- `4h` -> confirmation
- `1h` -> trigger

Current tier logic is:

- aligned `12h + 4h + 1h` -> `standard`
- aligned `12h + 4h`, but `1h` not confirmed -> `probe_aligned`
- `12h` bias intact, `4h` flat, `1h` aligned -> `probe_partial`
- neutral `12h`, but `4h + 1h` aligned -> `probe_partial`
- counter-trend `1h` against aligned `12h + 4h` -> `off`

Current sizing translation is:

- `standard` -> use the full directional band
- `probe_aligned` -> cap target at `15%-25%`, single-order cap `15%`
- `probe_partial` -> cap target at `15%-20%`, single-order cap `15%`
- `off` -> `0%`

The practical intent is deliberately more aggressive than the earlier rollout:

- probe sizing is now meant to be meaningful, not symbolic
- aligned multi-horizon setups can still reach the full directional band in one to two orders
- direction discipline stays strict even though sizing is less timid

The LLM is allowed to interpret this structure, but only inside hard bounds:

- it may move sizing by at most one tier
- it may downgrade to `observe`
- it may not reverse a confirmed `12h + 4h` direction
- it may not exceed structured or hard risk caps
- it may not remove `reduce / exit / freeze`
- it may not bypass `event_action` limits such as `block_new_entry`, `block_add`, or `reduce_only`

## Portfolio Risk Overlay

The portfolio layer is now deliberately more aggressive than the first rollout.

It still protects against repeated crypto-beta exposure, but it no longer treats moderate same-direction stacking as an immediate freeze.

Current defaults are:

- `caution` when same-theme concentration reaches about `50%`
- `freeze` when same-theme concentration reaches about `75%`
- `caution` when net directional budget usage reaches about `50%`
- `freeze` when net directional budget usage reaches about `75%`

Portfolio `caution` now only downgrades `standard -> probe`.
It no longer auto-kills an already valid `probe`.

The design goal is:

- keep total capital utilization available up to the hard portfolio budget
- stop the system from treating BTC/ETH same-direction exposure as two separate high-conviction bets

## Model Uncertainty Overlay

The uncertainty layer is now deliberately more permissive than the earlier rollout.

Its job is to answer:

- are the base models disagreeing too much
- is the current regime estimate unstable
- is the model historically weak in this regime
- is the current input missing too much data

Current defaults are:

- `caution` when disagreement is about `0.20+`
- `freeze` when disagreement is about `0.32+`
- `caution` when regime instability is about `0.45+`
- `freeze` when regime instability is about `0.65+`
- `caution` when recent regime fit falls below about `0.37`
- `freeze` when recent regime fit falls below about `0.30`

Low-data warnings by themselves only cause `caution`.
They escalate to `freeze` only when paired with weak fit or larger disagreement.

Uncertainty `caution` now only downgrades `standard -> probe`.
It does not automatically kill an already valid `probe`.

## Important Execution Nuance

Opening and adding actions are capped by the strategy's single-order size and the global perps order cap.
Reduce and close paths are driven by the delta between current state and target state, so they should be read as de-risking moves rather than normal entry sizing.

## Default Global Perps Limits

The public baseline keeps these important hard caps:

- total exposure budget: `100%`
- max position share of exposure budget: `100%`
- max order share of exposure budget: `66%`
- max leverage: `5x`

These hard caps sit below the strategy layer and still apply even if strategy targets are more aggressive.
