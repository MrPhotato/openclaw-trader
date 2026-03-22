# 数据模型：Macro & Event Analyst

## 1. MacroEventSubmission

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `submission_id` | string | 提交 ID |
| `task_id` | string | 来源任务 ID |
| `generated_at` | datetime | 生成时间 |
| `events` | array[`MacroEventItem`] | 结构化事件列表 |

## 2. MacroEventItem

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `event_key` | string | 语义归并键 |
| `category` | string | 事件类别 |
| `severity` | string | 严重度 |
| `status` | string | `active/resolved/cancelled` |
| `summary` | string | `1-2` 句话摘要 |
| `time_horizon` | object | 事件时间窗口 |
| `affected_symbols` | array[string] | 影响币种 |
| `source_refs` | array[object] | 来源引用 |

## 3. MacroFollowupWindow

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `event_key` | string | high 级未来事件键 |
| `event_time` | datetime | 事件时间 |
| `rule_kind` | string | `13_task_window` 或 `12_task_window` |

## 4. 关系与约束

- `MacroEventSubmission` 是正式提交，不包含 `alert`
- `MacroEventItem.summary` 必须限制在 `1-2` 句话
- 直接沟通提醒不通过该数据模型表达
