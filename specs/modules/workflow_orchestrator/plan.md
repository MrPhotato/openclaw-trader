# 实施计划：Workflow Orchestrator

**规格文档**：`specs/modules/workflow_orchestrator/spec.md`
**计划日期**：2026-03-15

## 1. 执行摘要

本计划把 `workflow_orchestrator` 收口为统一主动入口、客观唤醒、生命周期管理和正式收口中心，重点澄清它在 `MEA` 工作流中的职责只到客观触发和状态收口，不进入内容路由。

## 2. 技术背景（Technical Context）

- **现有系统事实**：当前已有控制命令和状态记录模型，但仍带着旧的内容路由影子
- **目标边界**：统一主动控制入口、显式状态机、`MEA` 计时器、PM/RT 固定班次与正式收口
- **主要依赖**：`news_events`、`agent_gateway`、`memory_assets`
- **未知项 / 待确认项**：后台长驻扫描细节、daily report 状态机

## 3. 宪法检查（Constitution Check）

- 模块边界先于实现：控制面只做控制与状态，不做 Agent 内容解释
- 单一真相源：状态与收口记录进入 `memory_assets`
- 事件驱动与结构化可观测性：命令、状态和 `MEA` 计时器都必须可追踪

## 4. 第 0 阶段：研究与现状归档

- 对齐控制命令、状态机主状态和幂等要求
- 对齐 `MEA` 的 `2h` 计时器与 `NEWS_BATCH_READY` 重置规则
- 对齐 PM 正式策略里的 `scheduled_rechecks[]` 消费规则

## 5. 第 1 阶段：设计与契约

- 定义控制命令、命令回执、状态记录和 `MEA` 计时器实体
- 明确 `workflow_orchestrator` 不订阅 `MEA` 结果内容
- 明确 `workflow_orchestrator` 只消费 PM 正式策略中的 recheck 元数据
- 明确 `high` 级事件不再由 `workflow_orchestrator` 托管跟踪

## 6. 第 2 阶段：任务分解与迁移路径

- 先统一主规格和 contracts
- 再回写旧 `003` 与总览文档
- 最后在代码层同步命令、状态和调度语义

## 7. 产物清单

- `research.md`
- `data-model.md`
- `contracts/`
- `quickstart.md`
- `tasks.md`
- `analysis.md`
