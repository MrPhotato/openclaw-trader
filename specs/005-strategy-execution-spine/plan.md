# 实施计划：策略与执行主脊梁

**功能分支**：`codex/005-strategy-execution-spine`
**规格文档**：`specs/005-strategy-execution-spine/spec.md`
**计划日期**：2026-03-11

## 1. 执行摘要

本 feature 负责把“策略 -> 执行上下文 -> 执行决策 -> 执行计划 -> 执行结果”链路的核心实体和动作收口成可实现的契约。它不处理 Agent 上下文和通知，只定义确定性主脊梁。

## 2. 技术背景（Technical Context）

- **现有系统事实**：当前策略与执行逻辑分散在 strategy、dispatcher 和 runtime 中，旧候选链已不再是新主工作流真相。
- **目标边界**：只定义策略意图与执行链路，不定义上下文拼装、不定义通知、不定义前端。
- **主要依赖**：`003` 的状态机控制平面，`004` 的市场与风险输出。
- **未知项 / 待确认项**：第一批停在 `ExecutionContext`，第二批再将 `ExecutionDecision` 真正接回执行主链。

## 3. 宪法检查（Constitution Check）

- 本地结构化实体控制策略与执行边界，符合 LLM 受约束自治。
- 主脊梁被定义为显式实体和契约，符合模块边界和单一真相源。
- 可被状态机和回放引用，符合可观测性要求。

## 4. 第 0 阶段：研究与现状归档

- 提炼当前 active strategy 的核心语义。
- 提炼 `ExecutionContext` 和 `ExecutionDecision` 的最小可实现实体。
- 提炼执行模块的统一动作集合和返回结果。

## 5. 第 1 阶段：设计与契约

- 在 `data-model.md` 中定义：
  - `StrategyIntent`
  - `ExecutionContext`
  - `ExecutionDecision`
  - `ExecutionPlan`
  - `ExecutionResult`
- 在 `contracts/` 中定义：
  - `strategy-intent.schema.json`
  - `execution-context.schema.json`
  - `execution-decision.schema.json`
  - `execution-plan.schema.json`

## 6. 第 2 阶段：任务分解与迁移路径

- 任务聚焦文档、schema 和后续实现边界。
- 明确下游：
  - `006` 依赖 `ExecutionContext` 和 `ExecutionDecision`
  - `007` 依赖 `ExecutionResult`

## 7. 产物清单

- `research.md`
- `data-model.md`
- `contracts/`
- `quickstart.md`
- `tasks.md`
