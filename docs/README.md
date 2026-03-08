# Documentation Index

This repository runs a live perpetuals trading workflow around Coinbase INTX, OpenClaw agent orchestration, and a local runtime under `~/.openclaw-trader/`.

The documents below capture the production-oriented behavior of the project as it exists today.

- [system-overview.md](system-overview.md): component roles, message flow, and source-of-truth rules
- [config-and-runtime.md](config-and-runtime.md): config precedence, runtime layout, and what must stay out of git
- [strategy-and-risk.md](strategy-and-risk.md): signal states, sizing semantics, and risk-stage behavior
- [dispatch-and-sessions.md](dispatch-and-sessions.md): dispatcher flow, OpenClaw session targeting, and notification routing
- [operations.md](operations.md): service scripts, health checks, logs, maintenance, and recovery workflow
- [perps-convergence.md](perps-convergence.md): legacy-vs-active path inventory and cleanup guidance

Recommended reading order for a new maintainer:

1. `system-overview.md`
2. `config-and-runtime.md`
3. `strategy-and-risk.md`
4. `dispatch-and-sessions.md`
5. `operations.md`
