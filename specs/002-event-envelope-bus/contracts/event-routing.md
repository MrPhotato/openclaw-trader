# Event Routing

## 1. Event Type Families

- `market.*`：模块事实与标准化市场数据
- `workflow.*`：主动控制命令、状态迁移和调度事件
- `agent.*`：Agent 请求、回执、升级
- `execution.*`：预览、下单、回执和失败
- `notification.*`：通知命令和发送结果

## 2. Event Type 命名

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

## 3. 当前交付规则

- 结构化事件必须先落 `memory_assets`
- 进程内 `EventBus` 只承担发布、测试观察和 best-effort 镜像
- 通知、查询、回放和 monitor 以 `memory_assets` 或进程内调用为主
- 不定义外部消息中间件为正确性前提

## 4. 幂等要求

- 所有 durable 事件必须以 `event_id` 作为幂等键。
- 命令事件必须附带业务层 `command_id` 或等价字段。
- 同一 `trace_id` 下允许多事件，但不得复用同一 `event_id`。
