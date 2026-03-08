# Config and Runtime

## Runtime Layout

By default the mutable runtime lives under:

- `~/.openclaw-trader/config/`
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
- forecast horizon
- minimum probabilities and size scaling

## Current Repository Defaults

The repository defaults now encode a conservative-but-usable public baseline:

- strategy order shares: weak `10%`, medium `20%`, strong `30%`
- observe caps: position `15%`, order `15%`
- reduce caps: position `4%`, order `4%`
- fresh-news block window: `15` minutes
- owner routing placeholders: `owner-channel` and `user:owner`

These defaults are meant to be safe to publish. Private deployments should override them locally.

## What Must Stay Out of Git

Do not commit:

- `~/.openclaw-trader/secrets/coinbase.env`
- local runtime YAML with personal routing or private channels
- SQLite databases
- logs
- generated reports and journals

The public repository assumes those files exist locally and are deployment-specific.

## Practical Rule

If a value is personal, environment-specific, or operationally sensitive, it belongs in local runtime config.
If a value is a reusable baseline for the product, it belongs in repository defaults.
