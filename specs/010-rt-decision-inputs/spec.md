# 功能规格说明：RT 决策输入收口

**功能分支**：`codex/010-rt-decision-inputs`  
**创建日期**：`2026-04-09`  
**状态**：草案  
**输入描述**：优化 RT 的 runtime input 与 prompt flow，保持 agent-first 风格，同时减少重复读取、工具往返和上下文膨胀。

## 1. 背景与目标

当前 RT 的单轮运行经常耗时数分钟，主要原因不是模型本身，而是：
- 每轮重复读取大量稳定不变的 skill / reference 内容
- runtime pack 拉取后再被拆成多次读取
- RT 默认没有一个“先看什么、后看什么”的紧凑工作视图

目标是在不削弱 RT 思考质量的前提下，把输入结构改成：
- 常驻人格 / 边界继续常驻
- runtime pack 新增决策摘要层
- RT 默认先读摘要，再按需下钻

## 2. 当前系统基线

- RT 通过 `POST /api/agent/pull/rt` 获取单份 runtime pack
- runtime pack 已包含：
  - `market`
  - `strategy`
  - `execution_contexts`
  - `risk_limits`
  - `forecasts`
  - `news_events`
  - `recent_execution_thoughts`
  - `latest_rt_trigger_event`
  - `latest_risk_brake_event`
- 当前缺少专门面向 RT 决策的紧凑摘要层

## 3. 用户场景与验收

### 场景 1：RT 被条件触发唤醒

RT 被 workflow orchestrator 条件触发、heartbeat、PM 更新或 risk brake 唤醒后，应先看到一份可直接工作的摘要，而不是先手动翻遍 runtime pack。

**验收标准**

1. `pull/rt` 返回结果中包含 `rt_decision_digest`
2. `rt_decision_digest` 至少覆盖触发原因、组合快照、策略快照、重点币种和近期执行记忆

### 场景 2：RT 仍可在必要时深入查看原始字段

系统不应把 RT 变成机械执行器。摘要层是默认入口，但 RT 在遇到歧义时仍可继续查看原始字段。

**验收标准**

1. RT skill 明确要求“先看 digest，再按需下钻”
2. 原始 `execution_contexts`、`market.market_context`、`recent_execution_thoughts`、`news_events` 继续保留

## 4. 功能需求

- **FR-001**：`pull/rt` 必须返回 `rt_decision_digest`，作为 RT 默认工作视图。
- **FR-002**：`rt_decision_digest` 必须是紧凑摘要，不重复整个 runtime pack 的原始结构。
- **FR-003**：RT skill、runtime-inputs 和运行态 AGENTS 必须明确采用“digest first, drill down only when needed”的工作流。
- **FR-004**：`latest_risk_brake_event` 必须稳定暴露 `lock_mode`，避免 skill 与运行态字段不一致。

## 5. 非功能要求

- **NFR-001**：不削弱 RT 的 agent-first 特性；摘要层只能作为默认入口，不能取代原始上下文。
- **NFR-002**：摘要层应明显缩短 RT 的默认读取路径，减少不必要的工具往返。
- **NFR-003**：变更必须保持现有 `pull/submit` 合约兼容，不影响下游风控和执行链。

## 6. 关键实体

- **RT Runtime Pack**：RT 当前轮次的完整输入包，包含市场、策略、风控、执行和触发上下文。
- **RT Decision Digest**：从 RT Runtime Pack 提炼出的紧凑决策摘要，供 RT 先读先用。

## 7. 假设与约束

- 保留当前 RT 的正式提交接口与 JSON contract，不改 `submit/execution` 结构。
- 不在本 feature 中引入新的 system prompt 框架；先用现有 skill / workspace 文档收口默认工作流。

## 8. 成功标准

- **SC-001**：RT runtime pack 新增稳定可用的 `rt_decision_digest`
- **SC-002**：RT 提示链改成“摘要优先、按需下钻”
- **SC-003**：相关回归测试覆盖 digest 和 risk brake lock mode
