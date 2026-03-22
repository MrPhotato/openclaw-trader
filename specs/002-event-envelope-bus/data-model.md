# 数据模型：事件协议与总线骨架

## 1. EventEnvelope

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `event_id` | string | 全局唯一事件 ID |
| `trace_id` | string | 跨模块关联同一流程的 ID |
| `causation_id` | string | 直接上游事件 ID，可为空 |
| `module` | string | 事件产生模块 |
| `entity_type` | string | 事件对应的实体类型 |
| `entity_id` | string | 事件对应的实体 ID |
| `event_type` | string | 事件类型，例如 `workflow.command.accepted` |
| `event_level` | enum | `debug` / `info` / `warn` / `error` |
| `occurred_at` | datetime | 事件发生时间 |
| `schema_version` | string | 事件 schema 版本 |
| `payload` | object | 业务载荷 |
| `human_summary` | string | 面向回放和 UI 的简述 |

## 2. BusRouteDescriptor

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `exchange` | string | RabbitMQ exchange 名称 |
| `routing_key` | string | topic routing key |
| `publisher_module` | string | 发布模块 |
| `consumer_modules` | string[] | 订阅模块 |
| `delivery_mode` | enum | `fire_and_forget` / `durable` |
| `idempotency_key_source` | string | 幂等键来源 |

## 3. ParameterChangeRecord

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `change_id` | string | 变更 ID |
| `parameter_path` | string | 参数路径 |
| `old_value` | any | 旧值 |
| `new_value` | any | 新值 |
| `scope` | object | 生效范围 |
| `operator` | string | 操作者 |
| `change_reason` | string | 变更原因 |
| `requested_at` | datetime | 提交时间 |
| `approved_by` | string | 批准者，可为空 |
| `rollback_of` | string | 回滚引用，可为空 |

## 4. ParameterEffectiveEvent

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `change_id` | string | 对应参数变更 ID |
| `effective_at` | datetime | 生效时间 |
| `applied_scope` | object | 实际生效范围 |
| `applied_by_module` | string | 应用该变更的模块 |
| `result` | enum | `applied` / `rejected` / `deferred` |
| `details` | object | 失败或延后原因 |
