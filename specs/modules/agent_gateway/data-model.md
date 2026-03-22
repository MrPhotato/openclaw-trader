# 数据模型：Agent Gateway

## 1. FormalSubmissionTemplate

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `submission_type` | string | `news` / `strategy` / `execution` |
| `schema_ref` | string | 对应 schema 文件路径 |
| `prompt_ref` | string | 对应 prompt 说明路径 |
| `example_refs` | string[] | 示例文件路径 |
| `version` | string | 合同版本 |

## 2. ValidatedSubmissionEnvelope

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `envelope_id` | string | 本次校验包唯一 ID |
| `submission_kind` | string | `news` / `strategy` / `execution` |
| `agent_role` | string | `pm` / `macro_event_analyst` / `risk_trader` |
| `validated_at` | string | AG 完成准入校验的 UTC 时间 |
| `trace_id` | string | 关联追踪 ID |
| `schema_ref` | string | 命中的 schema 文件路径 |
| `prompt_ref` | string | 命中的 prompt 说明路径 |
| `payload` | object | Agent authored 正式提交内容；系统字段由下游真相层补齐 |

## 3. SessionResetRule

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `agent_role` | string | `pm` / `mea` / `risk_trader` / `crypto_chief` |
| `reset_command` | string | 固定为 `/new` |
| `trigger` | string | 由 `workflow_orchestrator` 在每日 `UTC 00:30` 统一触发 |

## 4. SchemaValidationFailure

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `submission_type` | string | `news` / `strategy` / `execution` |
| `agent_role` | string | 原提交 Agent |
| `schema_ref` | string | 当前 schema 路径 |
| `prompt_ref` | string | 当前 prompt 路径 |
| `validation_errors` | string[] | 校验错误列表 |
| `retry_instruction` | string | 固定要求“重新生成纯 JSON” |

## 5. AgentRuntimeInput

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `input_id` | string | 本次运行时输入唯一 ID |
| `agent_role` | string | `pm` / `mea` / `risk_trader` / `crypto_chief` |
| `task_kind` | string | 任务类型 |
| `payload` | object | 当前轮次的结构化事实包 |

## 6. RoutingRule

| 提交类型 | 默认消费者 |
| --- | --- |
| `news` | `memory_assets` |
| `strategy` | `memory_assets`、`workflow_orchestrator` |
| `execution` | `policy_risk`，通过后再进入执行域 |
