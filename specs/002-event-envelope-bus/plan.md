# 实施计划：事件协议与进程内总线骨架

**功能分支**：`codex/002-event-envelope-bus`
**规格文档**：`specs/002-event-envelope-bus/spec.md`
**计划日期**：2026-03-11

## 1. 执行摘要

本 feature 负责把 `001` 中仍然偏抽象的三条跨域平面，先落成后续可以直接复用的公共协议层。其中本轮优先固化：

- 统一事件信封
- 进程内事件总线基础交付语义与命名
- 参数治理的最小实体与事件

本轮不落业务模块实现，不改动现有交易逻辑，只提供后续 `003-007` 统一依赖的契约。

## 2. 技术背景（Technical Context）

- **现有系统事实**：当前系统已有 SQLite、reports、OpenClaw transcript 和日志，但没有统一事件协议和交付规则。
- **目标边界**：只定义公共协议，不定义状态机、不定义策略、不定义执行语义。
- **主要依赖**：`001` 中的 [`01-target-architecture.md`](specs/001-system-blueprint/architecture/01-target-architecture.md)、[`05-event-bus-topology.md`](specs/001-system-blueprint/architecture/05-event-bus-topology.md)、[`07-logging-replay-frontend.md`](specs/001-system-blueprint/architecture/07-logging-replay-frontend.md)、[`contracts/event-envelope.schema.json`](specs/001-system-blueprint/contracts/event-envelope.schema.json)。
- **未知项 / 待确认项**：本轮不保留未决问题，统一采用稳定 `event_type` 命名、事件版本字段 `schema_version`、参数变更显式携带 `scope/operator/change_reason` 作为默认方案。

## 3. 宪法检查（Constitution Check）

- 协议先于实现，满足“模块边界先于实现”。
- 公共协议显式定义事件与真相源边界，满足“单一真相源与显式状态机”的前置要求。
- 不把自然语言当协议，满足“事件驱动与结构化可观测性”。

## 4. 第 0 阶段：研究与现状归档

- 汇总现有 `001` 中关于事件、事件总线、参数治理的所有定义，统一成单一特性文档。
- 对齐当前代码中已有的 `trace_id`、brief、通知、OpenClaw transcript 事实，提炼为未来统一事件流的兼容来源。
- 明确本 feature 只提供协议，不提供实现。

## 5. 第 1 阶段：设计与契约

- 在 `data-model.md` 中定义 `EventEnvelope`、`EventRouteDescriptor`、`ParameterChangeRecord`、`ParameterEffectiveEvent`。
- 在 `contracts/` 中定义：
  - `event-envelope.schema.json`
  - `event-routing.md`
  - `parameter-change.schema.json`
- 在 `quickstart.md` 中给出后续 `003-007` 如何引用这些契约的最小使用说明。

## 6. 第 2 阶段：任务分解与迁移路径

- 任务聚焦为文档实现任务，不进入代码。
- 明确 `003-007` 的依赖关系：
  - `003` 依赖事件协议和命令事件
  - `004` 依赖市场与风险事件命名
  - `005` 依赖执行计划和执行结果事件命名
  - `006` 依赖 AgentTask/Reply 事件命名
  - `007` 依赖通知和回放消费规则

## 7. 产物清单

- `research.md`
- `data-model.md`
- `contracts/`
- `quickstart.md`
- `tasks.md`
