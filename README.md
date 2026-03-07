# openclaw-trader

Independent crypto trading runtime for OpenClaw.

This repository contains the trading runtime, dispatcher, strategy pipeline, and exchange integrations.
Local runtime state is stored outside the repository under the current user's home directory.

## Features

- Coinbase INTX perpetuals runtime
- Strategy refresh and trade-review loop
- Local dispatch briefs and daily reports
- Risk controls, panic lock, and cooldown handling
- FastAPI service and `otrader` CLI

## Local Runtime Layout

By default the runtime stores mutable state under:

- `~/.openclaw-trader/`

Typical local files include:

- config YAML files under `~/.openclaw-trader/config/`
- reports under `~/.openclaw-trader/reports/`
- secrets under `~/.openclaw-trader/secrets/`
- SQLite state under `~/.openclaw-trader/state/`

These files are intentionally not committed to the repository.

## Setup

1. Create and activate a Python 3.11+ virtual environment.
2. Install the package in editable mode:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

3. Prepare local runtime config and credentials under `~/.openclaw-trader/`.
4. Start the service or dispatcher using the scripts in `scripts/`.

## Commands

```bash
otrader run-server
otrader run-dispatcher
otrader strategy-refresh --reason manual_refresh --deliver
otrader perp-account --coin BTC
otrader perp-signal --coin BTC
```

## Notes

- Exchange credentials are loaded from local environment files outside git.
- Default owner/channel placeholders in this repository are intentionally generic and should be overridden in local config.
- This repository is safe to publish only if local runtime files and credentials remain outside version control.
