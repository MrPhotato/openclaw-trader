# RabbitMQ Routing

## 1. Exchange

- `oclt.events`：模块事实与结果事件
- `oclt.commands`：主动控制命令和调度命令
- `oclt.agents`：Agent 请求、回执、升级
- `oclt.notifications`：通知命令和发送结果

全部采用 `topic` 类型。

## 2. Routing Key 命名

统一格式：

- 事实事件：`<domain>.<entity>.<state>`
- 命令事件：`<domain>.<entity>.command.<action>`
- 失败事件：`<domain>.<entity>.failed`

示例：

- `workflow.command.accepted`
- `workflow.state.transitioned`
- `risk.policy.ready`
- `agent.reply.received`
- `notification.delivery.failed`

## 3. 基础队列

- `q.workflow-core`：消费工作流命令与状态事件
- `q.agent-gateway`：消费 Agent 请求与回执
- `q.execution-bridge`：消费执行相关事件
- `q.notifications`：消费通知命令与结果
- `q.replay-indexer`：消费所有可回放事件

## 4. 幂等要求

- 所有 durable 事件必须以 `event_id` 作为幂等键。
- 命令事件必须附带业务层 `command_id` 或等价字段。
- 同一 `trace_id` 下允许多事件，但不得复用同一 `event_id`。
