# 实施计划：Macro & Event Analyst

**规格文档**：`specs/agents/macro_event_analyst/spec.md`
**计划日期**：2026-03-15

## 1. 执行摘要

本计划把 `Macro & Event Analyst` 固化为“低频巡检 + 事件驱动唤醒”的新闻与事件分析角色，重点明确其正式提交只有结构化事件列表，直接提醒走 Agent 间沟通，不再通过 `alert` 字段或 `workflow_orchestrator` 内容转发。

## 2. 技术背景（Technical Context）

- **现有系统事实**：已有 `006`、`007` 的相关 feature spec，但没有独立 Agent 主规格
- **目标边界**：`2h` 巡检、`NEWS_BATCH_READY` 唤醒、`1-2` 句结构化事件、直接提醒 PM、不得自写记忆
- **主要依赖**：`news_events`、`workflow_orchestrator`、`memory_assets`、`agent_gateway`
- **未知项 / 待确认项**：暂无本轮新增未知项

## 3. 宪法检查（Constitution Check）

- LLM 受约束自治：MEA 可直接协作，但正式结果必须经模块收口
- 单一真相源：长期事件记忆只进入 `memory_assets`
- 事件驱动与结构化可观测性：正式事件提交必须结构化

## 4. 第 0 阶段：研究与现状归档

- 对齐 `MEA` 在新闻主线中的真实岗位职责
- 对齐 `MEA -> PM/RT` 直接提醒边界与无 `alert` 决议

## 5. 第 1 阶段：设计与契约

- 定义正式事件提交实体
- 明确直接沟通对象、正式提交通道和禁止事项
- 明确 OpenClaw 原生记忆搜索只读投影关系

## 6. 第 2 阶段：任务分解与迁移路径

- 先固化 Agent 主规格和 formal submission contract
- 再回写旧 `006/007` 与总览文档
- 最后在代码层补齐 `MEA` 运行入口和记忆读取能力

## 7. 产物清单

- `research.md`
- `data-model.md`
- `contracts/`
- `quickstart.md`
- `tasks.md`
- `analysis.md`
