# 实施计划：工作流控制平面

**功能分支**：`codex/003-workflow-control-plane`
**规格文档**：`specs/003-workflow-control-plane/spec.md`
**计划日期**：2026-03-11

## 1. 执行摘要

本 feature 把控制面收口成显式状态机与统一控制 API，作为后续所有业务模块的唯一主动入口。它复用 `002` 的事件协议和总线规则，不定义业务细节。

## 2. 技术背景（Technical Context）

- **现有系统事实**：当前主动流程和状态推进分散在 dispatcher 相关模块中。
- **目标边界**：只定义控制入口、工作流状态模型、命令受理与状态迁移。
- **主要依赖**：`002-event-envelope-bus` 的事件与 RabbitMQ 契约；`001` 的 [`04-state-machine.md`](specs/001-system-blueprint/architecture/04-state-machine.md) 与 [`08-external-interfaces.md`](specs/001-system-blueprint/architecture/08-external-interfaces.md)。
- **未知项 / 待确认项**：本 feature 统一采用“单控制入口 + 工作流实例记录 + 状态迁移事件”方案，不保留未决问题。

## 3. 宪法检查（Constitution Check）

- 所有主动入口收口在状态机与编排器模块，符合宪法。
- 控制平面不直接混入业务规则，符合模块边界先于实现。
- 所有迁移都可映射到结构化事件，符合显式状态机与可观测性原则。

## 4. 第 0 阶段：研究与现状归档

- 提炼当前 dispatcher 中的主要阶段和降级路径。
- 把旧 CLI / FastAPI 主动动作映射到未来统一控制命令。
- 收口工作流实例、命令受理、命令去重、状态迁移的最小模型。

## 5. 第 1 阶段：设计与契约

- 在 `data-model.md` 定义：
  - `ManualTriggerCommand`
  - `WorkflowStateRecord`
  - `WorkflowTransitionRule`
  - `WorkflowCommandReceipt`
- 在 `contracts/` 定义：
  - 统一控制 API OpenAPI
  - 工作流状态 schema
  - 命令事件与状态迁移事件约定
- 在 `quickstart.md` 说明旧入口如何映射到新控制平面。

## 6. 第 2 阶段：任务分解与迁移路径

- 任务聚焦文档与契约，不进入代码。
- 明确后续依赖：
  - `004` 使用工作流命令和状态事件
  - `005` 使用 trade candidate / execution 阶段钩子
  - `006` 使用等待 Agent / Agent 回执阶段
  - `007` 使用通知和回放消费工作流状态

## 7. 产物清单

- `research.md`
- `data-model.md`
- `contracts/`
- `quickstart.md`
- `tasks.md`
