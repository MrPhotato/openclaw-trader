# 实施计划：Trade Gateway

**规格文档**：`specs/modules/trade_gateway/spec.md`
**计划日期**：2026-03-15

## 1. 执行摘要

本计划把 `Trade Gateway` 固化为单一顶层模块，并在模块内明确 `market_data` 与 `execution` 两个子域的共享边界、正式资产和下游依赖关系。

## 2. 技术背景（Technical Context）

- **现有系统事实**：当前实现已经落在 `src/openclaw_trader/modules/trade_gateway/market_data` 与 `execution` 两个目录。
- **目标边界**：顶层只保留一个 `Trade Gateway`；对外提供标准化交易所事实和执行交付，不承担新闻、策略和硬风控职责。
- **主要依赖**：交易所适配器、PM 读取链路、`policy_risk`、`memory_assets`
- **未知项 / 待确认项**：暂无本轮新增未知项

## 3. 宪法检查（Constitution Check）

- 模块边界先于实现：通过单一模块 + 双子域表达
- 单一真相源：执行与市场正式资产最终进入 `memory_assets`
- LLM 受约束自治：不允许执行层自行补全策略语义

## 4. 第 0 阶段：研究与现状归档

- 对齐当前 `market_data` 和 `execution` 模型与旧 `004/005` 文档
- 删除“两个顶层模块”的残留表述

## 5. 第 1 阶段：设计与契约

- 定义市场事实、账户事实、市场上下文、执行计划和执行结果实体
- 明确 `market_data` 与 `execution` 的输入输出和不负责事项
- 固化与 `quant_intelligence`、`policy_risk`、PM/RT 读取链路的衔接面
- 固化 execution 的最小职责：已过风控命令的基础送单、技术重试与最小执行流水

## 6. 第 2 阶段：任务分解与迁移路径

- 先收口主规格和 contracts
- 再回写旧 feature specs 的模块映射说明
- 最后再决定代码层模型和事件名同步

## 7. 产物清单

- `research.md`
- `data-model.md`
- `contracts/`
- `quickstart.md`
- `tasks.md`
- `analysis.md`
