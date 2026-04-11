# 数据与领域模型

本文件不是现有数据库 schema 的逐表抄录，而是为未来模块化重构定义统一的领域实体与事件实体。

## 1. 顶层领域实体

### 1.1 模块（ModuleDescriptor）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `module_id` | string | 模块唯一标识，例如 `quant-intelligence` |
| `name` | string | 中文展示名称 |
| `domain_type` | enum | `core` / `supporting` / `delivery` |
| `responsibilities` | string[] | 负责事项 |
| `non_responsibilities` | string[] | 不负责事项 |
| `owned_sources` | string[] | 该模块拥有的真相源 |
| `inbound_ports` | string[] | 输入端口 |
| `outbound_ports` | string[] | 输出端口 |

### 1.2 信息源（InformationSource）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `source_id` | string | 信息源唯一标识 |
| `owner_module` | string | 归属模块 |
| `category` | enum | `market` / `news` / `risk` / `strategy` / `execution` / `memory` / `control` |
| `freshness_sla` | string | 时效要求 |
| `truth_source` | string | 真相源位置 |
| `serialization` | string | 序列化格式 |

### 1.3 角色化运行时输入（AgentRuntimeInput）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `input_id` | string | 运行时输入标识 |
| `agent_role` | string | 消费者 Agent |
| `task_kind` | string | 服务任务类型 |
| `payload` | object | 角色所需的结构化事实包 |

### 1.4 工作流状态（WorkflowStateRecord）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `workflow_id` | string | 一次流程实例 ID |
| `state` | string | 当前状态 |
| `reason` | string | 状态迁移原因 |
| `trace_id` | string | 跨模块追踪 ID |
| `last_transition_at` | datetime | 最近迁移时间 |
| `payload_ref` | string | 关联事件或文档引用 |

### 1.5 手动触发命令（ManualTriggerCommand）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `command_id` | string | 命令 ID |
| `command_type` | string | `refresh_strategy` / `rerun_trade_review` / `replay` 等；其中 `rerun_trade_review` 为兼容命令名，语义上对应重跑执行判断 |
| `initiator` | string | 发起人或系统来源 |
| `scope` | object | 作用范围，例如 coin / 时间窗口 |
| `params` | object | 命令参数 |
| `requested_at` | datetime | 提交时间 |

### 1.6 Agent 任务（AgentTask）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_id` | string | 任务 ID |
| `agent_role` | enum | `pm` / `risk_trader` / `macro_event_analyst` / `crypto_chief` |
| `task_kind` | string | 任务类型 |
| `input_id` | string | 使用的运行时输入包 |
| `reply_contract` | string | 输出契约 |
| `trace_id` | string | 关联追踪 ID |

## 2. 关键决策实体

### 2.1 正式策略提交（StrategySubmission）

定义 PM 某个周期内对组合的正式目标描述，而不是直接订单。

核心字段：

- `strategy_id`
- `strategy_day_utc`
- `change_reason`
- `targets[]`
- `thesis`
- `invalidation`
- `scheduled_rechecks[]`
- `source_context_ref`

### 2.2 执行上下文（ExecutionContext）

定义某次执行判断所需的正式上下文，但不直接给出预生成动作。

核心字段：

- `context_id`
- `product_id`
- `strategy_version`
- `market_snapshot`
- `account_snapshot`
- `risk_limits`
- `position_risk_state`
- `forecast_snapshot`

### 2.3 执行决策（ExecutionDecision）

定义 `Risk Trader` 正式提交的结构化执行判断。

核心字段：

- `decision_id`
- `context_id`
- `action`
- `side`
- `notional_usd`
- `leverage`
- `reason`

### 2.4 执行计划（ExecutionPlan）

定义要提交给下单模块的确定性动作。

核心字段：

- `plan_id`
- `action` (`open` / `add` / `reduce` / `close` / `flip`)
- `side`
- `margin_usd`
- `notional_usd`
- `leverage`
- `guard_conditions`
- `created_from_decision_id`

## 3. 统一事件实体

### 3.1 事件信封（EventEnvelope）

所有日志、进程内事件发布和回放都统一使用该结构。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `event_id` | string | 全局唯一事件 ID |
| `trace_id` | string | 跨模块追踪 ID |
| `causation_id` | string | 直接上游事件 ID |
| `module` | string | 产生事件的模块 |
| `entity_type` | string | 作用实体类型 |
| `entity_id` | string | 实体 ID |
| `event_type` | string | 事件类型 |
| `event_level` | enum | `debug` / `info` / `warn` / `error` |
| `occurred_at` | datetime | 发生时间 |
| `schema_version` | string | 事件 schema 版本 |
| `payload` | object | 业务载荷 |
| `human_summary` | string | 供前端展示的人类可读摘要 |

### 3.2 参数变更记录（ParameterChangeRecord）

用于记录人工调参与生效范围。

核心字段：

- `change_id`
- `parameter_path`
- `old_value`
- `new_value`
- `scope`
- `operator`
- `approved_by`
- `effective_at`
- `rollback_of`

## 4. 与当前系统的映射

- 当前 `StateStore` 对应未来的状态与记忆管理模块中的一部分持久化能力。
- 当前 `strategy-day.json` / `dispatch-brief.json` / journal 文件对应未来的策略意图、工作流状态快照和回放索引。
- 当前 `AutopilotDecision`、`DecisionPolicyResult`、`LlmTradeReviewDecision` 将在未来分别对应工作流状态载荷、策略/风控快照和 `Risk Trader`/Agent 正式回执。
