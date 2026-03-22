# RabbitMQ 拓扑与消息总线

## 1. 目标

RabbitMQ 不是业务模块，而是跨域通信骨架。它解决三类问题：

1. 模块之间的异步协作
2. 多 Agent 请求与回执不丢失
3. 前端、回放、通知对事件流的实时消费

## 2. 推荐交换机

| 交换机 | 类型 | 用途 |
| --- | --- | --- |
| `oclt.facts` | topic | 原始事实与标准化数据 |
| `oclt.decisions` | topic | 量化判断、风险边界、策略与执行判断 |
| `oclt.workflow` | topic | 状态机状态迁移与工作流事件 |
| `oclt.agents` | topic | Agent 请求、回执与升级 |
| `oclt.execution` | topic | 下单命令、预览与回执 |
| `oclt.notifications` | topic | 通知命令与发送结果 |
| `oclt.replay` | fanout | 供回放与前端消费的标准事件镜像 |
| `oclt.control` | direct | 外部主动触发命令 |

## 3. 建议路由键

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

## 4. 队列建议

| 队列 | 绑定主题 | 消费者 |
| --- | --- | --- |
| `q.quant.inputs` | `market.*`, `news.event.*` | 量化判断模块 |
| `q.risk.guard` | `quant.prediction.ready`, `news.event.materialized`, `market.account.updated` | 风控与执行守卫模块 |
| `q.strategy.intents` | `risk.guard.decision.ready`, `workflow.command.accepted` | 策略与组合意图模块 |
| `q.agent.requests` | `agent.*.requested` | 多智能体协作网关 |
| `q.execution.orders` | `execution.order.submitted` | 账户与下单模块 |
| `q.notifications` | `notifications.*` | 通知服务模块 |
| `q.replay` | 全量镜像 | 回放与前端模块 |

## 5. 消息设计原则

- 同一业务事件只定义一种 canonical routing key。
- 每条消息都必须包裹在统一 `EventEnvelope` 中。
- 业务 payload 不得依赖文本 prompt 才能解释。
- 所有命令类消息都必须有回执消息。
- 所有失败都必须有结构化失败事件，而不是只留 stderr。

## 6. 当前系统迁移建议

第一阶段不要求立刻把所有模块改成 RabbitMQ 原生消费。可以先：

1. 保留当前函数调用链
2. 在关键节点补发结构化事件
3. 让 RabbitMQ 先承担镜像、通知和前端观察用途
4. 再逐步把跨模块调用改造成消息驱动
