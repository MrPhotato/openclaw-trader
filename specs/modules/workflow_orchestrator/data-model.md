# 数据模型：Workflow Orchestrator

## 1. ManualTriggerCommand

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `command_id` | string | 幂等 ID |
| `command_type` | string | 控制命令类型 |
| `initiator` | string | 发起者 |
| `scope` | object | 作用范围 |
| `params` | object | 扩展参数 |
| `requested_at` | datetime | 请求时间 |

## 2. WorkflowCommandReceipt

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `command_id` | string | 对应命令 ID |
| `accepted` | boolean | 是否接收 |
| `reason` | string | 接收或拒绝原因 |
| `workflow_id` | string? | 对应工作流 ID |
| `trace_id` | string? | 追踪 ID |
| `received_at` | datetime | 接收时间 |

## 3. WorkflowStateRecord

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `workflow_id` | string | 工作流 ID |
| `trace_id` | string | 追踪 ID |
| `state` | string | 当前状态 |
| `reason` | string | 转移原因 |
| `last_transition_at` | datetime | 最近迁移时间 |
| `payload_ref` | string? | 关联载荷引用 |

## 4. MEATimerState

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `timer_id` | string | 计时器 ID |
| `next_due_at` | datetime | 下次基础巡检时间 |
| `last_trigger_reason` | string | 上次触发原因 |
| `last_reset_at` | datetime | 最近重置时间 |

## 4.1 ExternalCadenceWakeup

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `agent_role` | string | 被固定班次唤醒的 Agent |
| `scheduled_at_utc` | datetime | 预定班次时间 |
| `delivered_at_utc` | datetime | 实际送达时间 |
| `source` | string | 固定为外部调度器，例如 `openclaw_cron` |
| `cadence_label` | string | `pm_0100` / `pm_1300` / `rt_10m` / `mea_2h` / `chief_2300` |

## 5. StrategyRecheckRegistration

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `strategy_id` | string | 来源策略 ID |
| `recheck_at_utc` | datetime | 到点时间 |
| `scope` | string | `portfolio` 或相关 symbol |
| `reason` | string | 留给未来的一句话 |

## 6. 关系与约束

- `ManualTriggerCommand.command_id` 必须用于幂等判定
- `MEATimerState` 只能由客观事件或计时器推进
- `ExternalCadenceWakeup` 只表示固定班次已送达，不替代 `WorkflowStateRecord`
- `workflow_orchestrator` 不以 `MEA` 结果内容为状态推进前提
- `StrategyRecheckRegistration` 只能来自通过 AG 校验的 PM 正式策略
