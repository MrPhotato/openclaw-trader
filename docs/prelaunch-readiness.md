# Post-Launch Gap Tracker

> **History note**: this file started (2026-03-15) as a pre-launch P0/P1/P2 checklist. All those blocking items have shipped and SOL has been retired from the live plane (2026-04-17). The original checklist is preserved in git history. This file is now a lightweight tracker for gaps observed in live operation. The authoritative module / agent contracts live under `specs/modules/` and `specs/agents/`.

## What the live system looks like today

- Tracked coins: `BTC`, `ETH` (SOL retired)
- Four agents with skill-based main-session model: PM / RT / MEA / Chief, all reachable at `agent:<role>:main`
- Workflow Orchestrator runs three-layer scheduling in-process (see [dispatch-and-sessions.md](dispatch-and-sessions.md))
- `runtime_pack.macro_prices` carries Brent / WTI / DXY / US10Y / Fear & Greed / BTC ETF activity from a unified `MacroDataService`
- MEA has `digital-oracle` (14 free financial APIs) wired via `scripts/digital_oracle_query.py` for market-price reality checks before escalating high-impact news
- Harness panels: `since_last_strategy` (PM), `your_recent_impact` (MEA) — surface necessity hints rather than enforce hard rate limits
- Weekly retrain: Sunday 12:07 SGT, full-horizon BTC + ETH, driven by launchd

## Known gaps worth watching

### Agent behaviour

- **RT alarm spam**: RT can send the same warning to PM multiple times in short windows (observed 2026-04-18 Brent loop). MEA has a `your_recent_impact` panel; RT does not yet have the symmetric "your_recent_pings_to_pm" mirror. Until that lands, RT skill rules are the only guardrail.
- **Cross-agent feedback loops**: MEA→PM→RT→PM chains still possible when a single event produces multiple downstream wakes. The harness approach (panels, not gates) means loops can still form — monitor for tight back-to-back PM revisions with identical change summaries.
- **Digital-oracle adoption**: vendored, `scripts/digital_oracle_query.py` ready. Real validation is whether MEA actually calls it before escalating. Watch `news_submission` impact-level distribution vs `digital_oracle_query.py` call count per MEA session.

### Runtime / data plane

- **Stale event-derived views**: historical event records (e.g. `risk_brake_event`) are frozen at capture time. Reconciliation against live state assets is now explicit for `risk_brake_event.lock_mode`; other event→view paths should be audited for similar drift patterns.
- **Macro feed freshness on weekends**: Brent / DXY / 10Y are closed; `is_market_open: false` surfaces in `macro_prices`. Agents must read that flag rather than treat the number as live.
- **ETF flow is a proxy, not a flow**: `btc_etf_activity` gives IBIT/FBTC/ARKB daily close + volume + 20-day avg. Real per-day net flow numbers sit behind paid APIs. Accept the proxy or budget a paid source.

### Operations

- **No dispatcher daemon**: all scheduling is in-process inside the trader service. Restarting the trader restarts every monitor. There is no separate `run_dispatcher.sh` anymore.
- **Chief retro is WO-driven**: Chief has no openclaw cron job enabled. `RetroPrepMonitor` prepares briefs from PM/RT/MEA and only then wakes Chief via `AgentWakeMonitor` / direct `send_to_session`. If Chief fails to fire at the retro hour, check `retro_prep_state` + `agent_wake_state` assets before looking at openclaw cron.
- **`pm_recheck_state.completed_recheck_keys` is bounded**: retains the last 64 keys only. Older scheduled rechecks could in principle refire if the strategy keeps referencing them. Not observed; flagged as a cap to remember.

## Authoritative references

- Module contracts: `specs/modules/<module>/contracts/`
- Agent skills: `skills/<agent-name>/SKILL.md` + `skills/<agent-name>/references/`
- Runtime behaviour: `docs/system-overview.md`, `docs/dispatch-and-sessions.md`, `docs/operations.md`

When a gap here is closed, remove the bullet. When a new one is observed in live operation, add it here first so it doesn't get lost between Slack threads and commits.
