# Config and Runtime

## Runtime Layout

By default the mutable runtime lives under:

- `~/.openclaw-trader/config/`
- `~/.openclaw-trader/models/`
- `~/.openclaw-trader/reports/`
- `~/.openclaw-trader/state/`
- `~/.openclaw-trader/logs/`
- `~/.openclaw-trader/secrets/`

The repository only contains code, bootstrap defaults, scripts, and documentation.

## Config Precedence

Runtime config is loaded from local YAML files through `load_runtime_config()`.

Precedence is:

1. Local runtime YAML in `~/.openclaw-trader/config/*.yaml`
2. Repository defaults defined in `src/openclaw_trader/config.py`
3. Bootstrap seed values in `src/openclaw_trader/bootstrap.py` when missing config files are first created

Implication:

- Editing local YAML changes live behavior immediately on the next config load
- Editing repository defaults changes the baseline for fresh environments and the fallback behavior when local keys are omitted

## Key Config Files

### `app.yaml`

- service bind host and port
- whether live orders and live exits are enabled
- general polling and startup values

### `perps.yaml`

- active exchange adapter
- tracked coins
- exposure-budget limits
- max leverage

### `risk.yaml`

- drawdown thresholds for observe, reduce, and exit
- emergency exit behavior
- max live orders per day

### `strategy.yaml`

- daily rewrite schedule
- signal confidence thresholds
- target position ranges and single-order sizes
- funding hot scaling
- neutral override switch

### `dispatch.yaml`

- dispatcher scan interval
- daily report schedule
- reply channel and reply target
- agent request timeouts

### `workflow.yaml`

- entry mode
- signal/news/panic notification cooldowns
- fresh-news blocking window
- owner channel and owner target

### `model.yaml`

- model training and feature settings
- fixed forecast horizons with `1h / 4h / 12h`
- minimum probabilities and size scaling
- Binance bootstrap snapshots plus local Coinbase snapshot accumulation
- fee-aware labeling and walk-forward calibration settings

## Model Runtime Artifacts

`market-intelligence` persists trained artifacts under:

- `~/.openclaw-trader/models/perps/<COIN>/<HORIZON>/`

Important outputs are:

- `meta.json`: compact status and calibration source of truth
- `regime.joblib`: HMM regime artifact
- `classifier.joblib`: direction and trade-quality artifacts
- `calibration-report.json`
- `calibration-report.md`

These files are runtime state. They should not be treated as repository source files or committed artifacts.

## Current Repository Defaults

The current branch baseline is an aggressive-but-structured multi-horizon setup:

- directional sizing bands:
  - weak `15%-25%`, order `15%`
  - medium `30%-50%`, order `25%`
  - strong `50%-70%`, order `35%`
- probe policy sizing:
  - aligned probe cap `25%`
  - partial probe cap `20%`
  - probe single-order cap `15%`
- risk-stage caps:
  - observe position/order `15%`
  - reduce position/order `4%`
- fresh-news block window: `15` minutes
- owner routing placeholders: `owner-channel` and `user:owner`
- multi-horizon model defaults:
  - `forecast_horizons = {1h: 4, 4h: 16, 12h: 48}`
  - `bootstrap_snapshot_exchange = binance_usdm`
  - portfolio caution/freeze around `50% / 75%`
  - uncertainty caution/freeze thresholds widened for a less defensive live policy

These defaults are meant to be safe to publish. Private deployments should override them locally.

## What Must Stay Out of Git

Do not commit:

- `~/.openclaw-trader/secrets/coinbase.env`
- local runtime YAML with personal routing or private channels
- trained model artifacts under `~/.openclaw-trader/models/`
- SQLite databases
- logs
- generated reports and journals

The public repository assumes those files exist locally and are deployment-specific.

## Practical Rule

If a value is personal, environment-specific, or operationally sensitive, it belongs in local runtime config.
If a value is a reusable baseline for the product, it belongs in repository defaults.
