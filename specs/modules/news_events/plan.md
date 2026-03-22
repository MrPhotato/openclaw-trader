# 实施计划：News Events

**规格文档**：`specs/modules/news_events/spec.md`
**计划日期**：2026-03-15

## 1. 执行摘要

本计划把 `news_events` 固化为新闻原始批次模块，只负责固定源、轻去重、标准化批次与 `NEWS_BATCH_READY`，并与 `MEA`、`workflow_orchestrator`、`memory_assets` 的边界对齐。

## 2. 技术背景（Technical Context）

- **现有系统事实**：当前已有 `NewsDigestEvent` 模型和直接轮询适配器，但事件名仍是 `news.synced`
- **目标边界**：新闻模块只到批次和客观事件，不承担语义归并和长期记忆
- **主要依赖**：固定源抓取器、`workflow_orchestrator`、`Macro & Event Analyst`
- **未知项 / 待确认项**：源清单细节、补抓语义、游标恢复

## 3. 宪法检查（Constitution Check）

- 模块边界先于实现：新闻与事件记忆分离
- 单一真相源：长期事件记忆留给 `memory_assets`
- 事件驱动与结构化可观测性：`NEWS_BATCH_READY` 是客观事件

## 4. 第 0 阶段：研究与现状归档

- 对齐固定源、去重和批次输出规则
- 从旧 `news.synced` 语义迁移到 `NEWS_BATCH_READY`

## 5. 第 1 阶段：设计与契约

- 定义 `NewsBatch` 和 `NewsBatchReadyEvent`
- 明确轻去重和批次就绪的正式边界
- 明确 `MEA` 只读批次，不把普通事件分发写回本模块

## 6. 第 2 阶段：任务分解与迁移路径

- 先统一主规格和 contracts
- 再同步旧 specs 的迁移说明
- 最后在代码层收敛事件名与批次模型

## 7. 产物清单

- `research.md`
- `data-model.md`
- `contracts/`
- `quickstart.md`
- `tasks.md`
- `analysis.md`
