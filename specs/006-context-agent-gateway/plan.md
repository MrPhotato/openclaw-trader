# 实施计划：上下文视图与多智能体网关

**功能分支**：`codex/006-context-agent-gateway`
**规格文档**：`specs/006-context-agent-gateway/spec.md`
**计划日期**：2026-03-11

## 1. 执行摘要

本 feature 负责把 LLM 协作层从当前散装 prompt 和单 Agent 逻辑中剥离出来，定义统一的运行时输入和多 Agent 网关契约。

## 2. 技术背景（Technical Context）

- **现有系统事实**：当前 `crypto-chief` 承担策略、审核、事件整理、owner 沟通和 Learning 多重职责。
- **目标边界**：只定义视图、Agent 契约和 OpenClaw 网关边界，不定义具体模型、不定义通知或状态存储实现。
- **主要依赖**：`004` 的信息源、`005` 的交易主脊梁、`002` 的事件协议、`003` 的控制平面。
- **未知项 / 待确认项**：默认以 4 Agent 目标态写契约，并保持对当前单 Agent 运行态的兼容解释。

## 3. 宪法检查（Constitution Check）

- LLM 在本地契约和视图边界内自治，符合宪法。
- OpenClaw 作为外部协作环境被显式隔离，符合模块化原则。
- 升级与回执都通过结构化事件表达，符合可观测性原则。

## 4. 第 0 阶段：研究与现状归档

- 整理当前 `crypto-chief` 的职责混杂点。
- 提炼四种目标角色的最小职责与输入输出边界。
- 提炼当前 workspace 和 OpenClaw 运行方式中的必要约束。

## 5. 第 1 阶段：设计与契约

- 在 `data-model.md` 中定义：
  - `AgentRuntimeInput`
  - `AgentTask`
  - `AgentReply`
  - `AgentEscalation`
- 在 `contracts/` 中定义：
  - `agent-task.schema.json`
  - `agent-reply.schema.json`

## 6. 第 2 阶段：任务分解与迁移路径

- 任务聚焦视图和契约，不进入代码实现。
- 明确下游：
  - `007` 消费 Agent 回执与升级事件，形成状态、通知和回放读模型。

## 7. 产物清单

- `research.md`
- `data-model.md`
- `contracts/`
- `quickstart.md`
- `tasks.md`
