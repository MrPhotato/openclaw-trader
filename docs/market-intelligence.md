# Market Intelligence

## Purpose

`market-intelligence` is the local signal and calibration subsystem that sits inside the perp runtime.

It is responsible for:

- turning candle history into supervised features
- adding perp-specific market structure features such as funding, premium, open interest, and day volume
- classifying direction as `short`, `flat`, or `long`
- estimating whether a predicted trade is worth taking after fees
- classifying coarse market regime
- calibrating execution thresholds and size ratios from walk-forward results
- writing machine-readable and human-readable calibration artifacts

This subsystem replaces the old idea of a single lightweight classifier. The legacy `openclaw_trader.ml` package now exists only as a compatibility shim.

It now trains and serves three fixed horizons in parallel:

- `1h` = `4` bars
- `4h` = `16` bars
- `12h` = `48` bars

`1h` remains a computed compatibility horizon, but it no longer participates in the main decision chain. The main structured market facts now come from `4h` and `12h`.

## Code Boundary

Primary code lives here:

- `src/openclaw_trader/market_intelligence/features.py`
- `src/openclaw_trader/market_intelligence/pipeline.py`

Main entry points:

- `PerpModelService`
- `PerpModelService.predict_multi()`
- `PerpModelService.train_all_horizons()`

Primary callers:

- `src/openclaw_trader/perps/runtime/__init__.py`
- `src/openclaw_trader/strategy/__init__.py`

## Mental Model

The subsystem works in four layers:

1. Feature building
2. Model training and prediction
3. Trade-quality and execution-policy calibration
4. Multi-horizon fact export
5. Artifact and status reporting

At runtime it is still consumed as one service, but these layers matter when debugging behavior changes.

There is now also a horizon split:

1. shared feature preparation
2. per-horizon training and calibration
3. multi-horizon status and structured fact export
4. runtime compatibility layer where `predict()` may still expose `1h`, but the main path consumes `4h/12h`

## Multi-Horizon Structured Facts

On top of the raw `1h / 4h / 12h` predictions, the subsystem now produces a structured market fact package.

The current mapping is:

- `12h` -> primary directional anchor
- `4h` -> primary confirmation and structure horizon
- `1h` -> computed diagnostic only; not consumed by the main decision chain

The structured output includes:

- direction and confidence by horizon
- regime
- diagnostics
- disagreement summary

The runtime and downstream modules now consume these outputs as structured market facts, not as a live policy layer.

## Feature Inputs

### Candle-derived features

Built from the tracked product's OHLCV history:

- short and medium returns
- rolling volatility
- candle range and body
- moving averages and MA spread
- breakout and breakdown distance
- drawdown
- trend persistence
- volume z-score and volume impulse
- short-vs-long momentum and range expansion ratios

### Cross-asset reference features

For non-BTC coins, the service also aligns BTC candles and adds:

- BTC feature mirrors such as `btc_ret_24`
- relative spreads such as `rel_ret_24_vs_btc`

This lets ETH and SOL reasoning incorporate a simple market leader reference without building a fully separate multi-asset model.

### Time-context features

Each training row now also carries lightweight time-context features derived from candle timestamps:

- hour-of-day sin/cos
- weekday sin/cos
- weekend flag
- coarse Asia / Europe / US session indicators

These are meant to capture repeat intraday structure without introducing a separate scheduling subsystem into the model.

### Perp market snapshot features

When state snapshots exist, the service aligns historical perp snapshots to candle timestamps and adds:

- funding rate
- premium
- open interest change
- day notional volume change
- snapshot coverage

For non-BTC coins it also adds BTC-relative perp market features.

These snapshots are recorded by the perp runtime before signal evaluation.

Historical coverage now uses a mixed source model:

- `Coinbase` snapshots are the native live source and keep accumulating locally
- `Binance USD-M` snapshots are allowed as a bootstrap history source for training coverage

This lets newly trained artifacts use perp-structure features earlier instead of waiting for many days of local Coinbase-only history.

## Training Logic

### Fee-aware labels

Training is no longer based on raw future move alone.

The supervised target uses:

- forecast horizon from `model.yaml`
- target move threshold
- round-trip cost estimate

The effective threshold is:

- `target_move_threshold_pct + round_trip_cost_pct`

That means weak moves that would be erased by fees are more likely to be labeled `flat`.

### Base direction models

The current direction layer is a light ensemble:

- `LightGBM` multiclass classifier
- `LogisticRegression` multiclass classifier

The service computes walk-forward out-of-fold predictions and derives a blend weight from validation macro F1 instead of hardcoding one model as the winner.

### Regime model

The regime layer uses a `GaussianHMM`.

It clusters market states, then maps state ids into three human labels:

- `bearish_breakdown`
- `neutral_consolidation`
- `bullish_trend`

The regime model is a supporting context layer, not the only trading decision-maker.

## Event Layer

`market-intelligence` now also exposes a structured event layer, built from existing news feeds but separated from directional prediction.

The current event layer normalizes:

- `event-calendar`
- `macro`
- `regulation`
- `exchange-status`
- `exchange-announcement`
- `official-x`
- `structured-news`

Each structured event includes:

- `event_type`
- `severity`
- `effective_window`
- `risk_state`
- `action_state`
- `scope`
- `scheduled`
- `execution_risk`
- `block_new_entry / block_add / block_flip`
- `allow_trim_only`
- `max_size_tier`

This layer is currently a structured environment input, not a direct directional model. It is exposed through:

- `perp-model-status`
- `perp-market-events`
- `strategy-input`
- `dispatch-brief`

It does not directly generate long/short signals.

Instead, the event stack now works in two stages:

1. normalize each news item into a structured `MarketEvent`
2. aggregate active events into one `EventActionSummary`

The summary currently resolves:

- `normal`
- `caution`
- `freeze`
- `reduce_only`

and turns that into action limits such as:

- allow only `probe`
- block new entry
- block add
- block flip
- trim/exit only

This means the event layer now directly constrains execution behavior without becoming a directional model.

## Portfolio Risk And Model Uncertainty

The decision stack now also computes two extra summaries before exposing a final policy:

- `event_action`
- `portfolio_risk`
- `model_uncertainty`

### Portfolio risk

This summary is built from the live BTC/ETH/SOL perp portfolio and answers:

- how much net directional exposure already exists
- how concentrated same-direction risk is
- how much budget remains after a simple correlation penalty

The current output includes:

- `total_net_directional_exposure_usd`
- `total_net_directional_exposure_share`
- `same_theme_concentration`
- `correlation_adjusted_remaining_budget_usd`
- `same_direction_positions`
- `risk_state`

Current aggressive defaults are:

- `caution` at about `50%` same-theme concentration
- `freeze` at about `75%` same-theme concentration
- `caution` at about `50%` net directional budget usage
- `freeze` at about `75%` net directional budget usage

This preserves total portfolio utilization up to the hard budget, but stops the runtime from treating repeated BTC/ETH/SOL exposure as three fully independent bets.

### Model uncertainty

This summary is derived from the multi-horizon prediction bundle and model status.

It tracks:

- base-model disagreement between LightGBM and linear probabilities
- regime instability from regime confidence
- recent regime fit from validation / walk-forward metrics
- low-data warnings

The current output includes:

- `base_model_disagreement`
- `regime_instability`
- `recent_regime_fit`
- `low_data_warning`
- `uncertainty_state`

Current aggressive defaults are:

- `caution` when disagreement reaches about `0.20`
- `freeze` when disagreement reaches about `0.32`
- `caution` when regime instability reaches about `0.45`
- `freeze` when regime instability reaches about `0.65`
- `caution` when recent regime fit falls below about `0.37`
- `freeze` when recent regime fit falls below about `0.30`

Low-data warnings are treated as yellow flags by default.
They cause `caution` on their own, and only escalate to `freeze` when paired with weak fit or large disagreement.

### Overlay effect

Neither summary can introduce a new direction.

They are only allowed to tighten the live policy overlay:

- `standard -> probe`
- `probe -> off` only for stronger freeze conditions
- never the reverse

### Meta-label / trade-quality model

After direction probabilities are produced, a second classifier estimates whether the predicted trade is worth taking.

The trade-quality model:

- uses the base-model probabilities as inputs
- learns from fee-adjusted realized long and short returns
- is calibrated with isotonic regression

This is the main reason the subsystem now behaves more like "should this be traded" rather than only "which side is likely".

## Walk-Forward Calibration

Walk-forward validation now has two jobs:

- validate predictive quality
- calibrate execution policy

The service scans small grids around the runtime defaults for:

- `min_confidence`
- `min_long_short_probability`
- `meta_min_confidence`
- `order_size_floor_ratio`
- `order_size_ceiling_ratio`

It first chooses a global policy, then optionally chooses regime-specific overrides when there is enough sample size.

This produces a calibrated policy bundle with:

- a global policy
- global outcome metrics
- optional overrides for bullish, bearish, and neutral regimes
- source marker `walk_forward_calibration`

If calibration is unavailable, prediction falls back to runtime defaults.

## Runtime Prediction Behavior

At prediction time the subsystem now:

1. refreshes or loads the trained artifacts
2. rebuilds the latest feature row
3. scores the base models
4. blends probabilities
5. estimates trade quality
6. resolves the calibrated execution policy for the current regime
7. suppresses weak trades back to `flat` when thresholds are not met
8. scales quote size from calibrated floor/ceiling ratios

The result is still a normal `SignalDecision`, so the rest of the perp runtime does not need a new interface.

For multi-horizon usage, `predict_multi()` returns one structured prediction bundle containing `1h`, `4h`, and `12h` results side by side. Runtime execution still starts from the `1h` path, but final entry gating can be changed by the multi-horizon policy overlay.

## Runtime Artifacts

Artifacts live under:

- `~/.openclaw-trader/models/perps/<COIN>/<HORIZON>/`

Examples:

- `~/.openclaw-trader/models/perps/BTC/1h/`
- `~/.openclaw-trader/models/perps/BTC/4h/`
- `~/.openclaw-trader/models/perps/BTC/12h/`

Important files:

- `meta.json`
- `regime.joblib`
- `classifier.joblib`
- `calibration-report.json`
- `calibration-report.md`

`meta.json` is the compact source of truth for:

- training row count
- validation scores
- feature names
- reference-feature list
- market-snapshot feature list
- walk-forward summary
- calibrated execution policy

## CLI and Status Surfaces

Useful commands:

```bash
otrader perp-model-status --coin BTC
otrader perp-model-train --coin BTC --all-horizons
otrader perp-model-train --coin BTC --horizon 4h
otrader perp-signal --coin BTC
otrader perp-shadow-policy --coin BTC
otrader perp-market-events --coin BTC
```

`perp-model-status` now exposes:

- feature names
- horizon name and horizon bars
- reference features
- market snapshot features
- calibrated policy
- calibration summary
- calibration report paths
- walk-forward summary
- `horizons`, which contains the `1h / 4h / 12h` status map
- the structured multi-horizon fact summary used by downstream modules

Prediction metadata also includes:

- model family names
- regime label and confidence
- blended probabilities
- trade-quality probability
- resolved execution policy
- whether the policy came from calibration or runtime defaults
- calibration report path

## Interaction With Other Modules

### Perps runtime

`PerpSupervisor` is still the runtime owner of the prediction flow.
It now records perp market snapshots before evaluation and delegates prediction to `PerpModelService`.

### Strategy layer

Strategy input generation reads `model_status()` and includes compact model metadata for each tracked product.

The LLM still sees a summarized view, not the full artifact payload. This is intentional so `crypto-chief` does not have to reason over raw calibration internals.

### Risk and execution

The subsystem now influences:

- whether a directional signal is suppressed back to `flat`
- the confidence attached to the signal
- the quote-size suggestion within runtime limits

It does not bypass:

- hard exposure caps
- drawdown-stage caps
- fresh-news gating and event-action masks
- exchange minimums
- final execution planning

## Operational Notes

- Branch changes do not hot-reload this subsystem. If checked-out code changes, restart trader and dispatcher.
- Model artifacts are local runtime state, not repository files.
- Missing or sparse perp snapshot history is allowed. The service falls back to candle-only features when snapshot coverage is insufficient.
- The compatibility package `openclaw_trader.ml` should be treated as transitional.
