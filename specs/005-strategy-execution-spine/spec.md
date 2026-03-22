# 功能规格说明：策略与执行主脊梁

> **迁移说明（2026-03-16）**：PM 的主规格现位于 `specs/agents/pm/`，正式 `strategy` 提交合同位于 `specs/modules/agent_gateway/contracts/strategy.schema.json`，`Trade Gateway` 与 `Risk Trader` 的主规格现位于 `specs/modules/trade_gateway/` 与 `specs/agents/risk_trader/`。本文件继续保留为横切的策略到执行 feature 文档。

**功能分支**：`codex/005-strategy-execution-spine`  
**创建日期**：2026-03-11  
**状态**：草案  
**输入描述**：定义策略意图、执行上下文、执行决策、执行计划和执行结果，作为新永续交易系统的主脊梁。

## 1. 背景与目标

`004` 已经定义了市场和风险结构化输出，`003` 已经定义了状态机与控制入口。`005` 的任务是把策略与执行之间的主脊梁写清楚，让系统从“量化边界”进入“目标仓位 -> 执行上下文 -> 执行决策 -> 执行计划 -> 执行结果”这条确定性路径。

本 feature 覆盖：

- 策略与组合意图模块
- `Trade Gateway` 内部 `execution` 子域

## 1.1 2026-03-12 收敛决议

经过新系统架构讨论，确认 PM 不再依赖独立的旧策略挂件模块。

本轮已经确认的方向：

- PM 通过 `agent_gateway` 的 `strategy` schema 正式提交目标组合与 `scheduled_rechecks[]`。
- `memory_assets` 持久化完整正式策略资产，`workflow_orchestrator` 只消费 recheck 元数据并触发 RT。
- PM 正式输出的是目标状态，不是执行路径。
- `TradeCandidate` 已从主链移除；系统不再通过预先生成的候选动作引导 `Risk Trader`。
- 主方向是由 `ExecutionContext` 驱动 `Risk Trader` 的自主决策，再由执行层消费其正式提交的 JSON 结构化结果。

## 1.2 2026-03-12 边界调整

原先独立的“账户与下单模块”不再作为顶层模块存在。

本 feature 后续负责的是：

- PM 正式策略与执行上下文
- `Trade Gateway` 内部 `execution` 子域消费的执行动作与结果

这意味着执行层仍然是独立子域，但顶层边界已经并入 `Trade Gateway`。

## 2. 当前系统基线

- 当前 active strategy 以 `strategy-day.json/md` 形式存在，本质上是目标仓位文档。
- 当前新系统第一批已经移除主链里的旧候选链，保留的是 `ExecutionContext` 和未来的 `ExecutionDecision` 协议。
- 当前执行层同时承担 preview、open、add、reduce、close、flip 等动作。
- 本 feature 必须依赖 `003` 的工作流状态机与 `004` 的市场/风险输出。

## 3. 用户场景与验收

### 场景 1：实现者需要确定性的策略到执行链路

实现者在重构时，不需要再从当前 runtime 和 dispatcher 大文件里推断“策略文档、旧候选链、执行判断、执行”之间如何衔接。

**验收标准**

1. 文档必须定义 `strategy` 正式提交、`ExecutionContext`、`ExecutionDecision`、`ExecutionPlan`、`ExecutionResult`。
2. 文档必须明确这些实体之间的先后关系和允许动作。

### 场景 2：后续 Agent 和执行实现只能在确定性边界内工作

Agent 不应直接给订单，执行模块也不应反向修改策略意图。

**验收标准**

1. 文档必须明确 `Risk Trader` 只基于 `ExecutionContext` 和硬边界产出执行决策。
2. 文档必须明确执行模块只消费 `ExecutionDecision`/`ExecutionPlan`，不自行生成策略。

## 4. 功能需求

- **FR-001**：系统必须定义 PM 的正式 `strategy` 提交，覆盖策略版本、变更原因、目标仓位、thesis、invalidation、scheduled rechecks。
- **FR-002**：系统必须定义 `ExecutionContext`，覆盖来源策略版本、当前仓位、市场信息、硬风控边界、账户状态和必要的执行约束。
- **FR-003**：系统必须定义 `ExecutionDecision`，其正式系统提交默认使用 JSON 输出并按币种 `decisions[]` 组织，动作集合为 `open`、`add`、`reduce`、`close`、`flip`、`wait`；无动作默认空列表。
- **FR-004**：系统必须定义 `ExecutionPlan` 和 `ExecutionResult`，并明确执行模块只消费结构化执行决策，不自行补全策略含义。
- **FR-005**：文档必须明确策略意图不等于订单，`Risk Trader` 基于 `ExecutionContext` 自主决策，执行链不得绕过硬风控边界。
- **FR-006**：本 feature 不定义上下文视图、不定义 Agent 路由、不定义通知语义。
- **FR-007**：第一批主工作流必须停在 `ExecutionContext`，不触发 Agent、执行层和交易通知链。

## 5. 非功能要求

- **NFR-001**：所有实体都必须足够稳定，可用于代码实现、Agent 消费和回放。
- **NFR-002**：动作命名、字段名和状态必须在 contracts、data model、tasks 中保持一致。
- **NFR-003**：策略到执行链路必须是可回放、可审计、可在状态机中定位的。

## 6. 关键实体

- **StrategySubmission**：PM 的正式策略提交，表达目标组合意图，不是订单。
- **ExecutionContext**：提供给 `Risk Trader` 的执行上下文，不直接携带建议性动作。
- **ExecutionDecision**：`Risk Trader` 的结构化执行决策，其正式系统提交通道默认使用 JSON 输出。
- **ExecutionPlan**：执行层可消费的确定性动作。
- **ExecutionResult**：下单或模拟执行结果。

## 7. 假设与约束

- 不兼容旧现货路径，只围绕新的永续执行主路径。
- 执行模块以统一动作集合为边界，不保留旧接口命名混杂语义。
- 具体交易所适配细节属于实现阶段，不在本 feature 中展开。
- 第一批允许执行模块保留计划对象和适配器，但它不在主工作流内被调用。

## 8. 成功标准

- **SC-001**：实现者可以仅基于 `005` 文档写出策略、review、执行主脊梁，而不需要再反推当前 dispatcher 大文件。
- **SC-002**：`006` 可以基于本 feature 的 `ExecutionContext` 和 `ExecutionDecision` 定义 Risk Trader 视图与回执协议。
- **SC-003**：`007` 可以基于本 feature 的 `ExecutionResult` 定义状态、通知和回放消费模型。
