# 事件协议与进程内总线拓扑

## 1. 目标

事件协议与进程内总线不是业务模块，而是跨域通信骨架。它解决四类问题：

1. 统一 `EventEnvelope` 与 `event_type` 命名
2. 模块之间的进程内发布与观察
3. 通过 `memory_assets` 保留持久化事件真相源
4. 支撑前端、回放、通知对事件流的消费

## 2. 当前推荐交付路径

| 阶段 | 责任 | 说明 |
| --- | --- | --- |
| 事件生产 | 业务服务创建 `EventEnvelope` | 事件类型稳定、载荷结构化 |
| 持久化 | 先写 `memory_assets` | 这是主正确性链与回放真相层 |
| 进程内发布 | `event_bus.publish(...)` | 仅承担本进程观察、测试与 best-effort 镜像 |
| 消费 | 通知、回放、查询、monitor | 以 `memory_assets` 和进程内调用为主，不依赖 broker |

## 3. 建议事件类型族

### 3.1 事实流

- `market.snapshot.updated`
- `market.candles.updated`
- `market.account.updated`
- `news.raw.collected`
- `news.event.materialized`

### 3.2 决策流

- `quant.prediction.ready`
- `risk.guard.decision.ready`
- `strategy.intent.ready`
- `execution.context.ready`
- `execution.decision.ready`

### 3.3 工作流流

- `workflow.state.entered`
- `workflow.state.exited`
- `workflow.command.accepted`
- `workflow.command.rejected`

### 3.4 Agent 流

- `agent.pm.requested`
- `agent.pm.replied`
- `agent.risk_trader.requested`
- `agent.risk_trader.replied`
- `agent.macro_analyst.requested`
- `agent.macro_analyst.replied`
- `agent.crypto_chief.requested`
- `agent.crypto_chief.replied`
- `agent.escalation.raised`

### 3.5 执行流

- `execution.preview.ready`
- `execution.order.submitted`
- `execution.order.acknowledged`
- `execution.order.failed`

## 4. 当前消费关系

| 事件类型族 | 主要生产者 | 当前主要消费者 |
| --- | --- | --- |
| `market.*` / `news.*` | `trade_gateway` / `news_events` | `quant_intelligence`、`policy_risk`、`agent_gateway` |
| `strategy.*` / `execution.*` | `agent_gateway` / `trade_gateway` | `memory_assets`、`notification_service`、`replay_frontend` |
| `workflow.*` | `workflow_orchestrator` | `memory_assets`、`notification_service`、查询接口 |
| `agent.*` | `agent_gateway` / OpenClaw 适配层 | `memory_assets`、`workflow_orchestrator`、前端回放 |
| `notification.*` | `notification_service` | `memory_assets`、前端回放 |

## 5. 消息设计原则

- 同一业务事件只定义一种 canonical `event_type`。
- 每条消息都必须包裹在统一 `EventEnvelope` 中。
- 业务 payload 不得依赖文本 prompt 才能解释。
- 所有命令类事件都必须有回执事件。
- 所有失败都必须有结构化失败事件，而不是只留 stderr。
- `memory_assets` 是事件真相层；进程内总线不能单独承担正确性。

## 6. 当前系统迁移建议

当前系统已经采用以下现实策略：

1. 保留当前函数调用链
2. 在关键节点补发结构化事件
3. 让进程内 `EventBus` 只承担轻量发布和测试观察用途
4. 让 `memory_assets`、通知和回放承担持久化与消费主链
