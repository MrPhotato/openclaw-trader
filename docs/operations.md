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

## Known Operational Edges

- network errors can still appear around exchange connectivity
- automated behavior depends on both the local trader runtime and the external OpenClaw agent environment
- screen or GUI permission issues belong to the host process running the agent tooling, not to the trader runtime itself

## Documentation Boundary

This repository documents the trader runtime and its assumptions.
Machine-specific process managers, GUI permission models, and personal owner-channel routing belong to the local deployment layer, not to the public repository defaults.
