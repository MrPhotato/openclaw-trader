# Operations

## Entry Points

This repository exposes two operational surfaces:

- FastAPI service via `otrader run-server`
- Typer CLI via `otrader ...`

Repository scripts wrap the common service processes:

- `scripts/run_server.sh`
- `scripts/run_dispatcher.sh`
- `scripts/run_maintenance.sh`

The scripts intentionally resolve the project root relative to the script path instead of depending on a machine-specific absolute path.

## Common Commands

```bash
otrader doctor
otrader run-server
otrader run-dispatcher
otrader strategy-refresh --reason manual_refresh --deliver
otrader perp-account --coin BTC
otrader perp-signal --coin BTC
otrader perp-model-status --coin BTC
otrader perp-shadow-policy --coin BTC
otrader perp-market-events --coin BTC
otrader perp-model-train --coin BTC --all-horizons
otrader dispatch-once
otrader maintenance
```

## Health and Verification

Typical checks:

- `GET /healthz`
- `otrader doctor`
- `otrader workflow`
- `otrader dispatch-once`

For local service verification, the health endpoint should return:

```json
{"status":"ok"}
```

## Logs and Maintenance

Maintenance handles:

- log rotation with gzip archives
- monthly archive splits for strategy and journal JSONL files
- database archival by table retention windows

Session archival code exists, but automatic session archival is disabled by default.

## Runtime State You Should Watch

Most operational debugging comes down to these locations:

- `~/.openclaw-trader/logs/`
- `~/.openclaw-trader/models/`
- `~/.openclaw-trader/reports/`
- `~/.openclaw-trader/state/trader.db`
- `~/.openclaw/logs/` when OpenClaw or channel routing is involved

## Recovery Checklist

After a local restart or deployment restart:

1. verify the service responds on `/healthz`
2. verify runtime config still points at the intended channel and exchange
3. verify the dispatcher is running
4. check recent logs for config, network, or exchange-status failures
5. run a safe read-only command such as `otrader doctor` or `otrader perp-account --coin BTC`

## Model Checks

For `market-intelligence`, the quickest operational checks are:

- `otrader perp-model-status --coin BTC`
- `otrader perp-signal --coin BTC`
- `otrader perp-shadow-policy --coin BTC`
- `otrader perp-market-events --coin BTC`

Look for:

- horizon map under `horizons`
- shadow-policy fields such as `bias`, `confirmation`, `trigger`, `size_tier`
- event-action summary fields such as `block_new_entry`, `block_add`, `allow_trim_only`
- training row count
- validation accuracy and macro F1
- calibrated-policy presence
- calibration report paths
- whether market snapshot features are present or empty

## Branch-Switch Caveat

Changing git branches does not hot-reload the running services.

If checked-out code changes for trader or dispatcher behavior, restart at least:

- trader
- dispatcher

Otherwise the live processes continue running whatever code was loaded when the Python processes started.

## Known Operational Edges

- network errors can still appear around exchange connectivity
- automated behavior depends on both the local trader runtime and the external OpenClaw agent environment
- screen or GUI permission issues belong to the host process running the agent tooling, not to the trader runtime itself

## Documentation Boundary

This repository documents the trader runtime and its assumptions.
Machine-specific process managers, GUI permission models, and personal owner-channel routing belong to the local deployment layer, not to the public repository defaults.
