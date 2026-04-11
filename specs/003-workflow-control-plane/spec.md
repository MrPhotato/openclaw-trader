# 功能规格说明：工作流控制平面

> **迁移说明（2026-03-15）**：`workflow_orchestrator` 的主规格现位于 `specs/modules/workflow_orchestrator/`，`Macro & Event Analyst` 的主规格现位于 `specs/agents/macro_event_analyst/`。本文件继续保留为横切控制平面 feature 文档。

**功能分支**：`codex/003-workflow-control-plane`  
**创建日期**：2026-03-11  
**状态**：草案  
**输入描述**：定义显式工作流状态机、统一主动控制入口和命令处理语义，作为模块化交易平台的核心控制平面。

## 1. 背景与目标

`001` 已经定义“所有主动入口统一收口在状态机与编排器模块”，`002` 又已经定义了事件协议和进程内总线规则。`003` 的任务是把这些原则变成可实施的控制平面：统一入口、统一命令语义、统一状态迁移和失败降级。

本 feature 只负责工作流控制平面，不直接定义量化、策略或 Agent 内容。

## 1.1 2026-03-14 事件分析工作流收敛决议

围绕 `news_events` 与 `Macro & Event Analyst` 的协同方式，本 feature 已确认以下控制平面规则：

- `news_events` 每 `5` 分钟轮询固定源，并在发现新批次新闻时发出 `NEWS_BATCH_READY` 事件。
- `workflow_orchestrator` 为 `Macro & Event Analyst` 维护一个基础 `2` 小时倒计时。
- 若在倒计时期间收到 `NEWS_BATCH_READY`，则立即触发 `Macro & Event Analyst`，并重置 `2` 小时倒计时。
- `Macro & Event Analyst` 产出结构化事件结果后，只进入 `memory_assets` 维护事件记忆真相源；`workflow_orchestrator` 不订阅也不转发 `Macro & Event Analyst` 的结果内容。
- `workflow_orchestrator` 在 `Macro & Event Analyst` 工作流中的职责收敛为客观唤醒、任务生命周期管理和正式结果收口，不承担 Agent 间内容路由。
- `Macro & Event Analyst` 与其他 Agent 的即时提醒、追问与协作可在 OpenClaw 中直接发生，但这些沟通本身不形成系统真相。
- 若 `Macro & Event Analyst` 记录了未来的 `high` 级事件，则系统层后续仍需支持 OpenClaw 官方托管式跟踪任务：
  - 若事件距离当前大于 `5` 小时，则一次性挂 `13` 个任务，覆盖 `event_time - 4h` 到 `event_time + 8h`，每小时一次。
  - 若事件距离当前不超过 `5` 小时，则从 `1` 小时以后开始，一次性挂 `12` 个任务，每小时一次。
  - 当前本 feature 只保留挂载规则，不提前把该正式提交流程绑定给 `workflow_orchestrator`。

## 2. 当前系统基线

- 当前系统真实流程散落在 `dispatch/__init__.py`、`dispatch/planning.py`、`dispatch/state_flow.py`、`dispatch/strategy_flow.py` 和 `dispatch/execution.py`。
- 当前已有 `dispatch-once`、`strategy-refresh`、`run-dispatcher` 等入口，但还没有统一控制 API。
- 当前已有 `heartbeat -> strategy -> trade_review -> execution` 的事实流程，但状态迁移未收口成单独契约。
- 本 feature 必须依赖 `002` 的事件协议和 事件路由 规则。

## 3. 用户场景与验收

### 场景 1：实现者需要统一主动触发入口

实现者在接入“刷新策略、重跑执行判断、发日报、重训模型、重放窗口”等操作时，不需要再次决定入口协议和命令生命周期。

**验收标准**

1. 必须定义单一控制 API 的命令 schema 和返回约定。
2. 必须说明命令被接受、拒绝、延迟和完成时分别产生哪些事件。

### 场景 2：实现者需要统一状态迁移规则

实现者要扩展策略、执行、Agent 或通知逻辑时，只能在显式状态机允许的迁移上工作，而不是在多个模块里各自推进流程。

**验收标准**

1. 必须定义主状态集合、迁移条件、失败状态和降级路径。
2. 必须定义工作流实例与 trace 的最小记录模型。

## 4. 功能需求

- **FR-001**：系统必须定义统一主动控制入口，接收至少 `refresh_strategy`、`rerun_trade_review`、`dispatch_once`、`sync_news`、`emit_daily_report`、`retrain_models`、`replay_window`、`pause_workflow`、`resume_workflow`。
- **FR-002**：系统必须定义显式工作流状态机，覆盖待受理、已受理、执行中、等待 Agent、待执行、已执行、已完成、已抑制、失败和降级等主状态。
- **FR-003**：系统必须定义工作流命令的幂等语义，包括 `command_id`、重复命令判定和去重行为。
- **FR-004**：系统必须定义工作流状态记录实体，使回放、通知和前端都能基于同一状态源工作。
- **FR-005**：本 feature 必须显式依赖 `002` 的 `EventEnvelope`，且不得重新定义事件顶层字段。
- **FR-006**：本 feature 不得定义量化判断、策略内容、Agent 上下文或执行细节，只负责控制平面。
- **FR-007**：系统必须支持 `NEWS_BATCH_READY` 触发 `Macro & Event Analyst` 的事件驱动唤醒，并在触发后重置其基础 `2` 小时倒计时。
- **FR-008**：系统必须将 `workflow_orchestrator` 在 `Macro & Event Analyst` 工作流中的职责限定为客观唤醒、生命周期管理和正式结果收口，而不是 `Macro & Event Analyst` 内容路由中心。
- **FR-009**：系统必须将 `Macro & Event Analyst` 的正式结构化结果交由 `memory_assets` 持久化；`workflow_orchestrator` 不得以订阅 `Macro & Event Analyst` 结果内容为前提推进下游协作。
- **FR-010**：系统必须支持未来 `high` 级事件的 OpenClaw 托管式跟踪调度，并明确 `13` 任务 / `12` 任务两种挂载规则；该正式提交流程的最终归属可在后续 feature 中继续收敛。

## 5. 非功能要求

- **NFR-001**：控制 API 必须是幂等可重放的，同一命令重复提交不会产生语义冲突。
- **NFR-002**：状态机命名、状态记录和事件命名必须足够稳定，可供前端直接消费。
- **NFR-003**：文档必须明确失败和降级路径，后续 feature 不能自行发明绕过控制平面的入口。
- **NFR-004**：控制平面不得自行维护 Agent 私有记忆文件；所有结构化事件记忆必须交由 `memory_assets` 负责持久化。

## 6. 关键实体

- **ManualTriggerCommand**：统一主动触发命令。
- **WorkflowStateRecord**：某次工作流的当前状态和最近迁移。
- **WorkflowTransitionRule**：状态迁移规则。
- **WorkflowCommandReceipt**：命令受理结果。

## 7. 假设与约束

- 控制平面优先围绕新的模块化系统设计，不兼容旧 spot 逻辑。
- 旧 CLI 和旧 FastAPI 接口未来视为适配层，本 feature 只定义新控制 API。
- 状态机只定义主干和降级路径，不在本 feature 中定义每个业务模块内部算法。

## 8. 成功标准

- **SC-001**：后续 `004-007` 都只能通过 `003` 的控制平面声明主动动作和状态迁移。
- **SC-002**：实现者可以仅根据 `003` 的 contracts 和 data model 搭出控制 API 与状态机骨架。
- **SC-003**：工作流状态、控制命令和降级语义在 `spec / plan / tasks / contracts` 中保持一致。
