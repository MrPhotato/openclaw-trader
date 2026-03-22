# 数据模型：工作流控制平面

## 1. ManualTriggerCommand

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `command_id` | string | 命令幂等 ID |
| `command_type` | string | 命令类型 |
| `initiator` | string | 发起人 |
| `scope` | object | 影响范围 |
| `params` | object | 命令参数 |
| `requested_at` | datetime | 提交时间 |

## 2. WorkflowCommandReceipt

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `command_id` | string | 对应命令 |
| `accepted` | boolean | 是否受理 |
| `reason` | string | 拒绝或受理原因 |
| `workflow_id` | string | 关联工作流 |
| `trace_id` | string | 追踪 ID |
| `received_at` | datetime | 受理时间 |

## 3. WorkflowStateRecord

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `workflow_id` | string | 工作流实例 ID |
| `trace_id` | string | 跨模块 trace ID |
| `state` | string | 当前状态 |
| `reason` | string | 当前状态原因 |
| `last_transition_at` | datetime | 最近迁移时间 |
| `payload_ref` | string | 关联载荷引用 |

## 4. WorkflowTransitionRule

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `from_state` | string | 起始状态 |
| `event_type` | string | 触发事件 |
| `to_state` | string | 目标状态 |
| `terminal` | boolean | 是否终止状态 |
| `fallback_to` | string | 失败时降级状态 |
