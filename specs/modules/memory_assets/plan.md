# 实施计划：Memory Assets

**规格文档**：`specs/modules/memory_assets/spec.md`
**计划日期**：2026-03-15

## 1. 执行摘要

本计划把 `memory_assets` 提升为除 `learning` 外所有真实资产的统一真相源，并重点定义 `MEA` 事件记忆、PM 正式策略资产、日摘要和只读记忆投影。

## 2. 技术背景（Technical Context）

- **现有系统事实**：当前已有工作流、事件、策略、组合、通知和回放 repository，但 MEA 资产尚未正式建模
- **目标边界**：统一真实资产写入、`MEA` 事件记忆、读模型和记忆投影
- **主要依赖**：`workflow_orchestrator`、`agent_gateway`、`notification_service`、OpenClaw 原生记忆投影
- **未知项 / 待确认项**：运行态真相完整清单、projection 更新时机、恢复与 journal 细节

## 3. 宪法检查（Constitution Check）

- 单一真相源：除 `learning` 外都由 `memory_assets` 持久化
- 事件驱动与结构化可观测性：资产均来自正式结构化提交
- LLM 受约束自治：Agent 不得直接写入长期记忆

## 4. 第 0 阶段：研究与现状归档

- 盘点现有 repository facade 与 `MEA` 相关缺口
- 对齐真实资产与协作痕迹边界

## 5. 第 1 阶段：设计与契约

- 定义 `MacroEventRecord`、`MacroDailyMemory`、`StrategyAsset`、`MemoryProjection`
- 明确 transcript 不是系统真相
- 明确 `memory_assets` 的写入前提和对外读面

## 6. 第 2 阶段：任务分解与迁移路径

- 先固化主规格与重点 contracts
- 再回写旧 `007` 和总览文档
- 最后在代码层补齐 MEA 资产与 projection

## 7. 产物清单

- `research.md`
- `data-model.md`
- `contracts/`
- `quickstart.md`
- `tasks.md`
- `analysis.md`
