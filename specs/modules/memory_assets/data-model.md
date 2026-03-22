# 数据模型：Memory Assets

## 1. StateSnapshot

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `snapshot_id` | string | 快照 ID |
| `trace_id` | string | 追踪 ID |
| `workflow_state` | object? | 工作流状态引用 |
| `portfolio_state` | object? | 组合状态引用 |
| `strategy_ref` | string? | 策略版本引用 |
| `snapshot_kind` | string | `light_15m` / `key_moment_full` |
| `trigger_kind` | string? | 若为关键节点快照，记录触发原因 |
| `captured_at` | datetime | 采集时间 |

## 2. StrategyAsset

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `strategy_id` | string | 正式策略 ID |
| `strategy_day_utc` | string | 所属 UTC 日 |
| `generated_at_utc` | datetime | 系统正式接收时间 |
| `trigger_type` | string | 本次唤醒/提交的系统触发类型 |
| `supersedes_strategy_id` | string? | 被替代的旧版本 |
| `revision_number` | integer | 最小版本链编号，从 `1` 开始 |
| `portfolio_mode` | string | 组合模式 |
| `target_gross_exposure_band_pct` | number[2] | 组合总目标暴露区间 |
| `portfolio_thesis` | string | 组合级解释 |
| `portfolio_invalidation` | string | 组合级失效条件 |
| `change_summary` | string | 相对上一版变化摘要 |
| `targets` | array | 每币目标与 RT 执行边界 |
| `scheduled_rechecks` | array | PM authored 的未来重看计划 |

## 3. MacroEventRecord

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `event_id` | string | 事件 ID |
| `event_key` | string | 语义归并键 |
| `category` | string | 类别 |
| `severity` | string | 严重度 |
| `status` | string | `active/resolved/cancelled` |
| `summary` | string | `1-2` 句话摘要 |
| `affected_symbols` | array[string] | 关联币种 |
| `source_refs` | array[object] | 来源引用 |
| `updated_at` | datetime | 最近更新时间 |

## 4. MacroDailyMemory

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `memory_day` | string | `UTC 00:00` 对应日 |
| `event_refs` | array[string] | 当日事件引用 |
| `summary` | string | 当日摘要 |
| `generated_at` | datetime | 生成时间 |

## 5. MemoryProjection

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `projection_id` | string | 投影 ID |
| `memory_scope` | string | 作用域 |
| `source_ref` | string | 来源 `memory_assets` 资产 |
| `projection_text` | string | 供召回的只读文本 |
| `synced_at` | datetime | 同步时间 |

## 6. ReplayQueryView

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `trace_id` | string? | 追踪 ID |
| `time_window` | object | 时间窗口 |
| `events` | array | 事件列表 |
| `states` | array | 状态列表 |
| `render_hints` | object | 渲染提示 |

## 7. 关系与约束

- `StrategyAsset` 存完整正式策略，不只存交易片段，也包含每币 RT 执行边界
- `StrategyAsset` 由系统从 PM authored submission materialize；不记录 PM 具体引用了哪些输入源
- `MacroEventRecord` 是 `MEA` 长期事件真相的最小单位
- `MacroDailyMemory` 只引用结构化事件，不复制原始新闻
- `MemoryProjection` 必须从 `memory_assets` 单向同步到原生语义记忆层
- `StateSnapshot` 只保留两类市场运行快照：`15m` 轻快照，以及关键节点全量快照
- 关键节点至少覆盖：PM 新策略、RT 正式决策、execution 提交前后/成交后、风控状态变化、MEA `high` 级提醒、每日复盘冻结点
