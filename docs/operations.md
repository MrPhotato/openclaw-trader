# Operations

## Entry Points

This repository exposes two operational surfaces:

- FastAPI service via `otrader run-server`
- Typer CLI via `otrader ...`

Repository scripts wrap the common service processes:

- `scripts/run_server.sh` — uvicorn entry used by launchd (`ai.openclaw.trader`)
- `scripts/run_maintenance.sh` — log rotation, archive splits, DB retention
- `scripts/run_weekly_retrain.sh` — Sunday 12:07 SGT (04:07 UTC) BTC/ETH full-horizon retrain, scheduled via `~/Library/LaunchAgents/ai.openclaw.trader.weekly-retrain.plist`

Agent-callable helpers (Python, called from agent `exec` tools):

- `scripts/pull_pm_runtime.py` — PM `/api/agent/pull/pm` wrapper + JSON drop
- `scripts/pull_rt_runtime.py` — RT equivalent with execution scaffold
- `scripts/pull_chief_retro.py` — Chief retro pack
- `scripts/digital_oracle_query.py` — wrapper over the vendored [digital-oracle skill](../skills/digital-oracle) for MEA's market-price reality check (Polymarket / CFTC COT / Deribit / F&G etc.). Use `--list-presets` for available scenarios.

The scripts intentionally resolve the project root relative to the script path instead of depending on a machine-specific absolute path.

The previous `run_dispatcher.sh` is gone. All automated wake and scheduling logic is now hosted **in-process** inside the FastAPI service via `WorkflowOrchestratorService` and its layered monitors (see [dispatch-and-sessions.md](dispatch-and-sessions.md)). There is no separate dispatcher daemon to manage.

## Common Commands

```bash
otrader doctor
otrader run-server
otrader strategy-refresh --reason manual_refresh --deliver
otrader perp-account --coin BTC
otrader perp-signal --coin BTC
otrader perp-model-status --coin BTC
otrader perp-shadow-policy --coin BTC
otrader perp-market-events --coin BTC
otrader perp-model-train --coin BTC --all-horizons
otrader maintenance
```

Cron / schedule inspection (helpful when a PM wake fires unexpectedly):

```bash
openclaw cron list --all --json            # includes disabled jobs
sqlite3 ~/.openclaw-trader/state/trader_v2.db "SELECT occurred_at, json_extract(payload_json, '\$.wake_source'), json_extract(payload_json, '\$.trigger_type') FROM events WHERE event_type='workflow.pm_trigger.detected' ORDER BY occurred_at DESC LIMIT 10;"
```

## Health and Verification

Typical checks:

- `GET /healthz` — liveness
- `otrader doctor` — configuration + exchange reachability

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
3. confirm the WO monitors are running — look for "workflow-orchestrator-*" threads in the process or check that `last_scan_at_utc` in assets like `pm_recheck_state`, `risk_brake_state`, `agent_wake_state` moves every scan interval
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

Changing git branches does not hot-reload the running service.

Restart the trader service (launchd `ai.openclaw.trader`) so the in-process Workflow Orchestrator monitors and agent gateway pick up the new code:

```bash
launchctl kickstart -k gui/$(id -u)/ai.openclaw.trader
```

Otherwise the live process continues running whatever code was loaded when Python started.

## Bridge 刷新延迟诊断

当 `RuntimeBridgeMonitor` 单次刷新 wall time 飙高时（症状：agent `pull/*` 卡顿，因为 cache stale 触发了 inline `refresh_once`，而 refresh 本身就慢），可以打开 `runtime_bridge.py` 里那段 env-flag 的 timing 仪器化代码，**无需改代码**就能看到每一段耗时分布。

开 → 重启 → 观察 → 关 → 重启：

```bash
launchctl setenv OPENCLAW_BRIDGE_TIMING 1
launchctl kickstart -k gui/$(id -u)/ai.openclaw.trader
# 等 ~2 分钟跑几个 cycle，然后看日志：
grep "\[bridge-timing\]" ~/.openclaw-trader/logs/trader.stderr.log | tail -20
launchctl unsetenv OPENCLAW_BRIDGE_TIMING
launchctl kickstart -k gui/$(id -u)/ai.openclaw.trader
```

每一行 `refresh_once` 会拆出各阶段 wall time：

```
[bridge-timing] refresh_once reason=scheduled total=16.7s primitives=5.5s forecasts=2.8s policies=0.0s build_inputs=5.0s payload_assemble=0.0s persist_portfolio=0.0s persist_bridge=0.0s
```

**健康值参考**（2026-04-25 基线，已完成 macro_data + market_data 并行 + targeted SQL helper 后）：

| 阶段 | 健康 | 黄牌 | 处置 |
|---|---|---|---|
| `total` | 12-20s | >40s | 钻进时间最长的子阶段 |
| `primitives` | 5-9s | >15s | 查 Coinbase HTTP 延迟 / DB 锁争用 |
| `forecasts` | 2-4s | >6s | quant 推理退化——查 `quant_intelligence` |
| `build_inputs` | 4-7s | >15s | 大概率是某个 panel 在扫太多行，grep 各 helper 找大 `limit=` 值 |
| `persist_*` | <1s | >3s | DB 锁争用；考虑开 WAL mode |

`[bridge-timing] primitive <name> done=Xs` 这些行（每个 `_collect_primitives` 子 future 一行）告诉你 6 个并行分支里哪个是长项——`market` 一般是 5-7s，其它都应该是亚秒级。

环境变量不设时这段代码完全不执行，**生产无成本**。

## Known Operational Edges

- network errors can still appear around exchange connectivity
- automated behavior depends on both the local trader runtime and the external OpenClaw agent environment
- screen or GUI permission issues belong to the host process running the agent tooling, not to the trader runtime itself

## Documentation Boundary

This repository documents the trader runtime and its assumptions.
Machine-specific process managers, GUI permission models, and personal owner-channel routing belong to the local deployment layer, not to the public repository defaults.
