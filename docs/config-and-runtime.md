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

Runtime config is loaded from local YAML files through `load_system_settings()` in `src/openclaw_trader/config/loader/`.

Precedence is:

1. Local runtime YAML in `~/.openclaw-trader/config/*.yaml`
2. Pydantic model defaults declared in `src/openclaw_trader/config/models.py`
3. Bootstrap seed values written when a fresh `~/.openclaw-trader/config/` directory is first initialised

Implication:

- Editing local YAML changes live behavior on the next service restart (no hot reload — see operations.md)
- Editing `config/models.py` defaults changes the baseline for fresh environments and the fallback behavior when local keys are omitted

## Key Config Files

### `app.yaml`

- service bind host and port
- whether live orders and live exits are enabled
- general polling and startup values

### `perps.yaml`

- active exchange adapter (Coinbase INTX)
- tracked coins — live baseline is `BTC` and `ETH` (SOL retired 2026-04-17, see `perps-convergence.md`)
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

Controls the Workflow Orchestrator's three-layer scheduler (see [dispatch-and-sessions.md](dispatch-and-sessions.md) for the architecture). Key blocks:

- **RuntimeBridgeMonitor** — `runtime_bridge_enabled`, `runtime_bridge_refresh_interval_seconds`, `runtime_bridge_max_age_seconds`. Background refresh of the shared runtime bundle (market + news + forecasts + macro_prices).
- **RTTriggerMonitor** — `rt_event_trigger_*`. Condition-driven RT wakes (strategy revisions, headline risk, exposure drift, heartbeat, execution follow-up).
- **PMRecheckMonitor** — `pm_scheduled_recheck_*`. Scans PM's `scheduled_rechecks` from the latest strategy and dispatches them into `agent:pm:main`.
- **RiskBrakeMonitor** — `risk_brake_*`. Drawdown-triggered reductions/exits plus PM wake.
- **RetroPrepMonitor** — `retro_prep_*`. Prepares briefs before waking Chief at the retro hour.
- **AgentWakeMonitor** (Layer 3, generic rule engine) — `agent_wake_enabled`, `agent_wake_scan_interval_seconds`, `agent_wake_rules` list. Each rule declares `agent`, `target_session_key`, `message_source.job_id`, `fire_when_any_of` predicates (`cron_time` and `max_silence_since`), and `cooldown_minutes`. Live baseline rule is `pm_main_heartbeat` — 01 UTC daily + 12 h silence fallback on `last_strategy_submit`.
- **MacroDataService** — `macro_data_enabled`, `macro_data_refresh_interval_seconds`, `macro_data_http_timeout_seconds`, `macro_data_etf_tickers`. Feeds Brent / WTI / DXY / US10Y via yfinance, Fear & Greed via alternative.me, and BTC ETF activity (IBIT/FBTC/ARKB volume + 20-day average) into `runtime_pack.macro_prices`.
- Reply channel (`reply_channel`, `reply_to`, `reply_account_id`) — owner-facing notification routing.
- Agent timeouts, openclaw binary path.

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
