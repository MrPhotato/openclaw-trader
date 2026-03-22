# openclaw-trader

Independent crypto trading runtime for OpenClaw.

This repository contains the local trading runtime, agent-facing bridge APIs, strategy and execution pipeline, Coinbase INTX integration, and a read-only public dashboard.

## Public Display

- Public dashboard: [https://openclaw-trader.mr-photato.com](https://openclaw-trader.mr-photato.com)
- The public site is read-only.
- Only query endpoints are exposed to the public dashboard.
- Control and agent endpoints remain private on the local runtime.

## What This Project Does

- Runs a local OpenClaw-connected crypto trading stack
- Lets PM, RT, MEA, and Chief agents work through agent-first runtime packs
- Stores strategy, execution, portfolio, and event state outside git
- Publishes a separate internet-facing dashboard for observation

## Architecture

The system is split into two parts:

1. Local runtime
   - Runs the actual trader service
   - Talks to OpenClaw, exchange APIs, and local state
   - Keeps control endpoints private

2. Public display
   - Serves a read-only frontend
   - Reads data through a query-only bridge
   - Cannot control the local OpenClaw or trader runtime

## Public Dashboard Model

The public site is intentionally display-only:

- `GET /api/query/*` is available to the dashboard
- `/api/control/*` is not exposed
- `/api/agent/*` is not exposed
- The cloud display uses cached query responses so the page can continue showing recent data even if the local tunnel temporarily disconnects

## Main Capabilities

- Coinbase INTX perpetuals portfolio and order flow
- PM strategy publication and revision history
- RT execution decisions, fills, and recent action feed
- MEA macro and event tracking
- Chief daily retro and summary workflow
- Query APIs for overview, replay, recent executions, and agent latest output
- Chinese read-only dashboard for public observation

## Runtime State

Mutable runtime state is intentionally stored outside the repository under the current user's home directory.

Typical local layout:

- `~/.openclaw-trader/config/`
- `~/.openclaw-trader/state/`
- `~/.openclaw-trader/reports/`
- `~/.openclaw-trader/secrets/`

These files are not meant to be committed.

## Requirements

- Python `>= 3.11`
- Node.js `>= 18`
- A local OpenClaw runtime
- Exchange credentials and local runtime configuration outside git

## Local Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
```

To build the frontend locally:

```bash
cd frontend
npm ci
npm run build
```

## Basic CLI Usage

After installing the package, the main CLI is:

```bash
otrader --help
```

Examples:

```bash
otrader serve
otrader command reset_agent_sessions
otrader workflow --help
otrader strategy --help
otrader portfolio --help
otrader events --help
otrader replay --help
```

## Repository Layout

- `src/openclaw_trader/` - backend application and modules
- `frontend/` - Vite frontend
- `scripts/` - local helper scripts
- `docs/` - project documentation
- `tests/` - backend and frontend-adjacent test coverage

## Documentation

- [docs/README.md](docs/README.md)
- [docs/system-overview.md](docs/system-overview.md)
- [docs/config-and-runtime.md](docs/config-and-runtime.md)
- [docs/market-intelligence.md](docs/market-intelligence.md)
- [docs/strategy-and-risk.md](docs/strategy-and-risk.md)
- [docs/dispatch-and-sessions.md](docs/dispatch-and-sessions.md)
- [docs/operations.md](docs/operations.md)
- [docs/perps-convergence.md](docs/perps-convergence.md)
- [docs/prelaunch-readiness.md](docs/prelaunch-readiness.md)
- [docs/v2-dev-comparison.md](docs/v2-dev-comparison.md)

## Security Notes

- Do not commit local config, keys, secrets, or exchange credentials
- Keep OpenClaw control surfaces private
- Treat the public dashboard as read-only infrastructure
- If you deploy a public copy, only expose query endpoints unless you add proper authentication and network isolation

## Publishing Notes

This repository is safe to publish only if:

- local runtime state remains outside git
- secrets stay outside git
- public deployment remains query-only
