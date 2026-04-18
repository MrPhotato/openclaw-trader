[English](README.md) | [简体中文](README.zh-CN.md)

# openclaw-trader

`openclaw-trader` is the trading runtime that sits behind the OpenClaw crypto workflow.

It owns:

- the local FastAPI service and CLI
- agent-facing runtime pack and formal submit bridges
- strategy, execution, replay, and portfolio query surfaces
- Coinbase INTX integration
- the React/Vite read-only dashboard

This repository is written for maintainers and developers. Runtime state, secrets, exchange keys, and local OpenClaw config all live outside git.

## Public Deployment

The current public read-only dashboard is:

- [https://openclaw-trader.mr-photato.com](https://openclaw-trader.mr-photato.com)

That site is intentionally query-only. Control and agent endpoints stay private on the local runtime.

## System Shape

There are two distinct runtime zones:

1. Local trading runtime
   - runs the actual trader service
   - talks to OpenClaw, exchange APIs, and local SQLite state
   - keeps `/api/control/*` and `/api/agent/*` private

2. Public display layer
   - serves the built frontend
   - reads data through a query-only bridge
   - uses cache on the cloud side so the dashboard can keep showing recent data during short local connectivity drops

Do not collapse those two zones unless you are intentionally redesigning the security model.

## Repository Layout

- [src/openclaw_trader](src/openclaw_trader) — backend application, modules, adapters, and CLI
- [frontend](frontend) — Vite/React dashboard
- [tests](tests) — backend and integration tests
- [scripts](scripts) — local helper scripts
- [docs](docs) — maintainer documentation
- [skills](skills) — agent skill packs (PM / RT / MEA / Chief). May also contain vendored third-party skills (e.g. [skills/digital-oracle](skills/digital-oracle) — MIT, [komako-workshop/digital-oracle](https://github.com/komako-workshop/digital-oracle)); each third-party skill ships its own `LICENSE` and attribution.

## Requirements

- Python `>= 3.11`
- Node.js `>= 18`
- npm
- a local OpenClaw runtime
- local runtime config and secrets outside the repo

## Runtime State Outside Git

Mutable state is intentionally stored under the current user's home directory.

Typical local paths:

- `~/.openclaw-trader/config/`
- `~/.openclaw-trader/state/`
- `~/.openclaw-trader/reports/`
- `~/.openclaw-trader/secrets/`
- `~/.openclaw/`

Do not commit those directories.

## Backend Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
```

CLI entrypoint:

```bash
otrader --help
```

Common commands:

```bash
otrader serve
otrader command reset_agent_sessions
otrader workflow --help
otrader strategy --help
otrader portfolio --help
otrader events --help
otrader replay --help
```

## Frontend Setup

```bash
cd frontend
npm ci
npm run dev
```

Useful frontend commands:

```bash
npm run test
npm run build
```

If `frontend/dist` exists when the backend starts, the FastAPI app will serve the built dashboard from `/`.

## Local Development Workflow

Typical loop:

1. start the backend with `otrader serve`
2. run the frontend dev server from [frontend](frontend)
3. point the frontend at the local API
4. verify query surfaces such as:
   - `/api/query/overview`
   - `/api/query/executions/recent`
   - `/api/query/replay`

When working on production behavior, always distinguish between:

- agent-first runtime pulls and submits
- public read-only display
- local private control surfaces

Those are not interchangeable.

## Testing

Backend tests are primarily standard-library `unittest` suites.

Typical examples:

```bash
uv run python -m unittest tests.test_v2_agent_gateway
uv run python -m unittest tests.test_v2_api_integration
uv run python -m unittest tests.test_v2_workflow_orchestrator
```

Frontend:

```bash
cd frontend
npm run test
```

## Documentation

Start here:

- [docs/README.md](docs/README.md)

Recommended reading order for a new maintainer:

1. [docs/system-overview.md](docs/system-overview.md)
2. [docs/config-and-runtime.md](docs/config-and-runtime.md)
3. [docs/market-intelligence.md](docs/market-intelligence.md)
4. [docs/strategy-and-risk.md](docs/strategy-and-risk.md)
5. [docs/dispatch-and-sessions.md](docs/dispatch-and-sessions.md)
6. [docs/operations.md](docs/operations.md)

Additional references:

- [docs/perps-convergence.md](docs/perps-convergence.md)
- [docs/prelaunch-readiness.md](docs/prelaunch-readiness.md)
- [docs/v2-dev-comparison.md](docs/v2-dev-comparison.md)

## Security and Publishing Notes

- Do not commit exchange credentials, OpenClaw secrets, or local runtime state.
- Do not expose `/api/control/*` or `/api/agent/*` publicly unless you add explicit authentication and network isolation.
- Treat the public dashboard as a display surface, not an operator console.
- If you are deploying a public copy, keep the cloud side query-only.
