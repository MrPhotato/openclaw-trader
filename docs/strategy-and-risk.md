# Strategy and Risk

## Mental Model

The strategy layer produces a target exposure, not a blind market order.

The runtime then asks:

- what side should the position be on
- how large should the target position be
- what single-order size is allowed
- whether current risk state or fresh news blocks the change

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
- default range: `10%-20%`
- default order share: `10%`

### `directional_medium`

- side is not flat
- confidence is at or above the weak threshold but below strong
- default range: `20%-40%`
- default order share: `20%`

### `directional_strong`

- side is not flat
- confidence is at or above the strong threshold
- default range: `40%-60%`
- default order share: `30%`

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

### Fresh-news block

Relevant fresh news forces the decision into `observe` for the configured freshness window.
The repository default is now `15` minutes.

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
