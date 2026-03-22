# 实施计划：Agent Gateway

**规格文档**：`specs/modules/agent_gateway/spec.md`
**计划日期**：2026-03-16

## 1. 执行摘要

本计划把 `agent_gateway` 固化为 Agent 协作层与正式提交准入层。它统一维护 `news`、`strategy`、`execution` 三类提交模板，负责 schema 校验和分发，但不承担长期记忆、策略版本化或执行语义解释。

## 2. 技术背景（Technical Context）

- **现有系统事实**：当前已区分直接沟通与正式提交，但仍缺少统一提交模板与共享 schema 契约
- **目标边界**：统一模板、统一准入、统一分发，不做重业务处理
- **主要依赖**：OpenClaw 运行时、`workflow_orchestrator`、`memory_assets`、执行域消费者
- **未知项 / 待确认项**：provider 级失败重试、session 粒度审计、异步超时策略

## 3. 宪法检查（Constitution Check）

- OpenClaw 继续是协作层，不是系统真相层
- 真实资产仍由对应模块消费后写入 `memory_assets`
- 下游不重复做 schema 准入校验，只消费各自语义

## 4. 第 0 阶段：研究与现状归档

- 对齐当前正式提交通道与升级事件模型
- 对齐三类模板与 prompt 拼接输入的共享方式

## 5. 第 1 阶段：设计与契约

- 定义 `news`、`strategy`、`execution` 三类 schema、prompt 说明与 examples
- 定义 `ValidatedSubmissionEnvelope`
- 明确 MQ 分发边界与消费者关系

## 6. 第 2 阶段：任务分解与迁移路径

- 先固化主规格与 contracts
- 再回写旧 `006` 与总览文档
- 最后在代码层实现统一校验与分发

## 7. 产物清单

- `research.md`
- `data-model.md`
- `contracts/`
- `quickstart.md`
- `tasks.md`
- `analysis.md`
