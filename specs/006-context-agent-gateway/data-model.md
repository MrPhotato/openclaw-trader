# 数据模型：上下文视图与多智能体网关

本文件只描述进入系统收口链的正式提交对象。Agent 间自由沟通不要求匹配这些 schema，也不直接形成系统真相。

## 1. AgentRuntimeInput

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `input_id` | string | 运行时输入 ID |
| `agent_role` | string | 输入服务的 Agent |
| `task_kind` | string | 当前任务类型 |
| `payload` | object | 结构化事实包 |

## 2. AgentTask

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_id` | string | 任务 ID |
| `agent_role` | string | `pm` / `risk_trader` / `macro_event_analyst` / `crypto_chief` |
| `task_kind` | string | 任务种类 |
| `input_id` | string | 所用运行时输入 |
| `reply_contract` | string | 正式回执契约，仅适用于系统提交 |
| `trace_id` | string | 追踪 ID |

## 3. AgentReply

`AgentReply` 表示某个 Agent 进入系统收口链的正式结构化回执，不用于约束 Agent 间的自由沟通内容。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_id` | string | 对应任务 |
| `agent_role` | string | 回执角色 |
| `status` | string | `completed` / `rejected` / `needs_escalation` |
| `payload` | object | 结构化结果 |
| `returned_at` | datetime | 返回时间 |

### 3.1 Macro & Event Analyst 回执负载

当 `agent_role = macro_event_analyst` 时，`payload` 至少应支持：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `events` | array | 语义归并后的事件列表 |

注：诸如 `MEA -> PM` 的即时提醒、追问和澄清不通过本 payload 建模，而是走 Agent 间直接沟通。

其中每条事件建议至少包含：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `event_key` | string | 语义归并键 |
| `title` | string | 事件标题 |
| `summary` | string | `1-2` 句话的精简描述 |
| `category` | string | 事件类别 |
| `severity` | string | `low / medium / high` |
| `time_scope` | string | `short / medium / long` |
| `event_time` | datetime/null | 事件时间，可为空 |
| `status` | string | `new / updated / resolved` |

## 4. AgentEscalation

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `escalation_id` | string | 升级 ID |
| `task_id` | string | 来源任务 |
| `agent_role` | string | 升级来源 |
| `reason` | string | 升级原因 |
| `requested_owner_decision` | boolean | 是否需要 owner 决策 |
