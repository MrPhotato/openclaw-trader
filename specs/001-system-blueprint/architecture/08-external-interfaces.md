# 对外接口与 OpenClaw 边界

## 1. 当前对外接口

### 1.1 CLI

当前 CLI 主要分为五类：

- 运行与诊断：`doctor`、`workflow`、`run-server`、`run-dispatcher`
- dispatcher / 策略：`dispatch-once`、`strategy-refresh`、`strategy-show`
- 量化与市场：`perp-snapshot`、`perp-signal`、`perp-model-status`、`perp-shadow-policy`
- 账户与下单：`perp-account`、`perp-open-paper`、`perp-close-paper`、`perp-open-live`
- 维护：`poll-news`、`maintenance`、`perp-backfill-binance-snapshots`

### 1.2 FastAPI

当前 HTTP 服务暴露：

- 健康与查询：`/healthz`、`/balances`、`/snapshot`、`/signal`、`/news`
- perps 查询：`/perps/snapshot`、`/perps/account`、`/perps/panic-lock`
- perps 操作：`/perps/open-paper`、`/perps/close-paper`、`/perps/open-live`、`/perps/panic-resume`
- workflow 查询与操作：`/workflow`、`/autopilot-check`、`/daily-report`、`/preview-buy`、`/panic-exit` 等

### 1.3 OpenClaw 集成

当前通过 `openclaw agent --agent <agent_id>` 与 `openclaw message send` 两种命令交互。

## 2. 目标对外接口

### 2.1 统一主动控制入口

未来系统对外只保留一个主动控制入口：

- `POST /api/control/commands`

它负责接收所有主动命令：

- `refresh_strategy`
- `rerun_trade_review`（兼容命令名，语义上对应重跑执行判断）
- `dispatch_once`
- `sync_news`
- `replay_window`
- `emit_daily_report`
- `retrain_models`
- `pause_workflow`
- `resume_workflow`

### 2.2 统一查询入口

建议保留查询型接口，但按读模型收口：

- `/api/query/workflows/{trace_id}`
- `/api/query/strategy/current`
- `/api/query/portfolio/current`
- `/api/query/replay`
- `/api/query/events`
- `/api/query/parameters`

## 3. OpenClaw 的独立边界

OpenClaw 必须被视为外部协作环境，而不是系统内部业务模块。

它只通过多智能体协作网关接入，职责是：

- 接受 AgentTask
- 返回结构化 Agent 回执
- 通过通知服务或 Crypto Chief 触达 owner

它不应直接：

- 写本地状态库
- 直接调用下单模块
- 直接修改策略真相源

## 4. 当前到目标的迁移原则

- 当前 CLI / FastAPI 不会立刻消失，但逐步退化为“适配层”。
- 未来所有主动动作都应转发到统一控制入口。
- OpenClaw 相关命令与 session 规则要收口到独立契约，而不是散落在 dispatcher 内部。
