# 实施计划：市场智能与风险守卫

**功能分支**：`codex/004-market-intelligence-guards`
**规格文档**：`specs/004-market-intelligence-guards/spec.md`
**计划日期**：2026-03-11

## 1. 执行摘要

本 feature 把数据接入与标准化、新闻事件、量化判断、风控守卫四个模块收敛为同一条结构化输入链。目标不是重写模型，而是定义所有后续模块都要使用的标准实体和输出边界。

## 2. 技术背景（Technical Context）

- **现有系统事实**：当前 live 永续主路径已稳定依赖 `1h/4h/12h`、组合风险、不确定性和硬风控边界，但这些能力已收敛到 `policy_risk`，而不是旧软建议层。
- **目标边界**：只定义结构化输入输出和职责边界，不定义策略、不定义执行、不定义 Agent prompt。
- **主要依赖**：`001` 中的量化与风控文档、`002` 的事件协议、`003` 的控制平面。
- **未知项 / 待确认项**：默认沿用当前永续主路径职责分层，不再保留旧 spot 兼容需求。

## 3. 宪法检查（Constitution Check）

- 协议先于实现，模块边界明确。
- 量化与风险边界受本地结构化约束控制，符合 LLM 受约束自治。
- 市场输出和守卫输出都可映射到统一事件协议，符合可观测性原则。

## 4. 第 0 阶段：研究与现状归档

- 从 `001` 的现有文档提炼：
  - 数据接入与新闻事实
  - 量化小模型职责分层
  - 风控与执行守卫语义
- 固化哪些是直接给后续模块的输出，哪些只是内部细节。

## 5. 第 1 阶段：设计与契约

- 在 `data-model.md` 中定义：
  - `MarketSnapshotNormalized`
  - `NewsEventMaterialized`
  - `MultiHorizonPredictionReady`
  - `RiskGuardDecisionReady`
- 在 `contracts/` 中定义：
  - 市场快照 schema
  - 新闻事件 schema
  - 风险守卫 schema

## 6. 第 2 阶段：任务分解与迁移路径

- 任务聚焦文档和契约，不进入实现代码。
- 明确依赖和下游：
  - `005` 只消费 `004` 的结构化输出
  - `006` 只消费 `004` 的信息源分类
  - `007` 只消费 `004` 发出的事件和读模型素材

## 7. 产物清单

- `research.md`
- `data-model.md`
- `contracts/`
- `quickstart.md`
- `tasks.md`
