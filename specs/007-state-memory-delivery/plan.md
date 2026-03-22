# 实施计划：状态、记忆与交付层

**功能分支**：`codex/007-state-memory-delivery`
**规格文档**：`specs/007-state-memory-delivery/spec.md`
**计划日期**：2026-03-11

## 1. 执行摘要

本 feature 负责把前六个 feature 的结构化结果落成状态、记忆、通知和回放/前端可消费的读模型，完成第一阶段模块化系统的交付层闭环。

## 2. 技术背景（Technical Context）

- **现有系统事实**：当前状态与交付素材分散在 SQLite、reports、jsonl、日志和 OpenClaw transcript。
- **目标边界**：只定义新系统所需的状态边界、通知契约和读模型，不复刻所有旧维护细节。
- **主要依赖**：`002-006` 的事件协议、控制平面、市场与风险输出、策略执行实体和 Agent 契约。
- **未知项 / 待确认项**：默认采用“事件流 + 读模型 + 最小状态快照”方案，不继续保留“零散文件即真相”的设计。

## 3. 宪法检查（Constitution Check）

- 单一真相源通过状态快照和读模型边界体现，符合宪法。
- 通知和回放消费结构化事件，符合可观测性原则。
- 不让 OpenClaw transcript 成为唯一记忆源，符合受约束自治原则。

## 4. 第 0 阶段：研究与现状归档

- 提炼当前 SQLite、reports、journal、transcript 中真正还需要保留的能力。
- 识别哪些是状态真相、哪些是记忆提炼、哪些只是观测素材。
- 为通知和回放定义最小可交付模型。

## 5. 第 1 阶段：设计与契约

- 在 `data-model.md` 中定义：
  - `StateSnapshot`
  - `MemoryView`
  - `NotificationCommand`
  - `NotificationResult`
  - `ReplayQueryView`
- 在 `contracts/` 中定义：
  - `state-snapshot.schema.json`
  - `notification-command.schema.json`
  - `replay-query.openapi.yaml`

## 6. 第 2 阶段：任务分解与迁移路径

- 任务聚焦文档、schema 和交付边界。
- 这一 feature 完成后，`001-007` 将形成完整文档链，可直接交给实现 agent。

## 7. 产物清单

- `research.md`
- `data-model.md`
- `contracts/`
- `quickstart.md`
- `tasks.md`
