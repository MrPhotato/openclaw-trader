# 数据模型：状态、记忆与交付层

## 1. StateSnapshot

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `snapshot_id` | string | 快照 ID |
| `trace_id` | string | 追踪 ID |
| `workflow_state` | object | 当前工作流状态 |
| `portfolio_state` | object | 当前组合摘要 |
| `strategy_ref` | string | 当前策略引用 |
| `captured_at` | datetime | 生成时间 |

## 2. MemoryView

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `memory_id` | string | 记忆视图 ID |
| `scope` | string | 作用范围 |
| `decision_refs` | array | 相关决策引用 |
| `learning_refs` | array | 相关学习引用 |
| `summary` | string | 提炼摘要 |

## 2.1 MacroEventRecord

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `event_id` | string | 事件记录 ID |
| `event_key` | string | 语义归并键 |
| `title` | string | 事件标题 |
| `summary` | string | `1-2` 句话摘要 |
| `category` | string | 事件类别 |
| `severity` | string | `low / medium / high` |
| `time_scope` | string | `short / medium / long` |
| `status` | string | `new / updated / resolved` |
| `event_time` | datetime | 事件时间，可为空 |
| `first_seen_at` | datetime | 首次记录时间 |
| `last_updated_at` | datetime | 最近更新时间 |
| `source_refs` | array | 来源引用列表 |

## 2.2 MacroDailyMemory

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `memory_date` | string | `UTC 00:00` 切分的日期 |
| `active_event_keys` | array | 当日仍活跃的事件键 |
| `new_event_keys` | array | 当日新增事件键 |
| `updated_event_keys` | array | 当日更新事件键 |
| `resolved_event_keys` | array | 当日解决事件键 |
| `summary` | string | 当日压缩摘要 |

## 2.3 MemoryProjection

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `projection_id` | string | 投影视图 ID |
| `memory_view_id` | string | 对应记忆视图 ID |
| `scope` | string | 投影作用域，例如 `macro_event_analyst` |
| `projection_text` | string | 供 OpenClaw 检索的压缩文本 |
| `source_event_keys` | array | 本投影引用的事件键 |
| `synced_at` | datetime | 最近同步时间 |
| `active` | boolean | 是否仍参与记忆检索 |

## 3. NotificationCommand

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `notification_id` | string | 通知 ID |
| `channel` | string | 目标渠道 |
| `recipient` | string | 接收人 |
| `message_type` | string | 消息类型 |
| `payload` | object | 消息载荷 |

## 4. NotificationResult

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `notification_id` | string | 对应通知 ID |
| `delivered` | boolean | 是否投递成功 |
| `provider_message_id` | string | 外部消息 ID |
| `failure_reason` | string | 失败原因，可为空 |
| `delivered_at` | datetime | 投递时间 |

## 5. ReplayQueryView

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `trace_id` | string | 查询 trace |
| `time_window` | object | 时间窗口 |
| `events` | array | 事件列表 |
| `states` | array | 状态快照 |
| `render_hints` | object | 前端展示建议 |
