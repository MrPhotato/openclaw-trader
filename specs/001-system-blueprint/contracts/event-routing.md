# 事件类型契约

## 1. 命名规则

- `event_type` 使用点分层级
- 事件命名使用过去时或完成态，例如 `strategy.intent.ready`
- 命令命名使用请求态，例如 `workflow.command.accepted`

## 2. 必备事件类型

- `market.snapshot.updated`
- `news.batch.ready`
- `quant.prediction.ready`
- `risk.guard.decision.ready`
- `strategy.intent.ready`
- `execution.context.ready`
- `execution.decision.ready`
- `workflow.state.entered`
- `agent.pm.requested`
- `agent.risk_trader.requested`
- `agent.macro_analyst.requested`
- `agent.crypto_chief.requested`
- `execution.order.submitted`
- `execution.order.acknowledged`
- `notification.requested`
- `notification.delivered`
- `parameter.changed`

## 3. 交付约束

- 任一模块只能依赖自己声明过的事件类型族。
- 任一模块发布事件前必须校验 `EventEnvelope` schema。
- 任一主链事件都必须先落 `memory_assets`，再做进程内 fan-out。
- 失败事件必须和原始 `trace_id` 保持一致。
