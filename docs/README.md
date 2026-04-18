# Documentation Index

This repository runs a live perpetuals trading workflow around Coinbase INTX, a four-agent orchestration (PM / RT / MEA / Chief), and a local runtime under `~/.openclaw-trader/`. Live tracked coins are `BTC` and `ETH`.

The documents below capture the production-oriented behavior of the project as it exists today.

- [system-overview.md](system-overview.md): component roles, message flow, and source-of-truth rules
- [config-and-runtime.md](config-and-runtime.md): config precedence, runtime layout, and what must stay out of git
- [market-intelligence.md](market-intelligence.md): multi-horizon models, event/portfolio/uncertainty overlays, fee-aware training, and model artifacts
- [strategy-and-risk.md](strategy-and-risk.md): signal states, sizing semantics, multi-horizon policy, and risk-stage behavior
- [dispatch-and-sessions.md](dispatch-and-sessions.md): Workflow Orchestrator's three-layer scheduler (AgentDispatcher → specialised monitors → AgentWakeMonitor), session-key contract, and notification routing
- [operations.md](operations.md): service scripts, health checks, logs, maintenance, and recovery workflow
- [perps-convergence.md](perps-convergence.md): legacy-vs-active path inventory and cleanup guidance, including the 2026-04 SOL retirement
- [v2-dev-comparison.md](v2-dev-comparison.md): diff between the current trader runtime and the `codex/dev` reference system

The `skills/` tree contains agent skills ([pm-strategy-cycle](../skills/pm-strategy-cycle/SKILL.md), [risk-trader-decision](../skills/risk-trader-decision/SKILL.md), [mea-event-review](../skills/mea-event-review/SKILL.md), [chief-retro-and-summary](../skills/chief-retro-and-summary/SKILL.md)) plus vendored third-party skills (currently [digital-oracle](../skills/digital-oracle), MIT — see its `LICENSE` and `README.md`).

Recommended reading order for a new maintainer:

1. `system-overview.md`
2. `config-and-runtime.md`
3. `market-intelligence.md`
4. `strategy-and-risk.md`
5. `dispatch-and-sessions.md`
6. `operations.md`
7. `perps-convergence.md`
