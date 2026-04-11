# 实施计划：PM

**规格文档**：`specs/agents/pm/spec.md`
**计划日期**：2026-03-16

## 1. 执行摘要

本计划把 PM 固化为组合经理角色：读结构化事实，形成目标组合，提交 `strategy` JSON，由 `agent_gateway` 校验后进入正式处理链，再由 `memory_assets` 和 `workflow_orchestrator` 分别消费。

## 2. 技术背景（Technical Context）

- **现有系统事实**：PM 已有 `UTC 01:00` / `UTC 13:00` 固定策略判断和事件驱动额外运行的工作方式，但旧文档仍把正式输出写成另一套策略对象
- **目标边界**：明确输入、触发、输出、输出路径和记忆策略，不定义执行路径
- **主要依赖**：`agent_gateway`、`memory_assets`、`workflow_orchestrator`、`quant_intelligence`、`policy_risk`、`Trade Gateway.market_data`
- **未知项 / 待确认项**：RT 策略级升级判定标准、未来更多 portfolio 级字段

## 3. 宪法检查（Constitution Check）

- PM 不自管长期记忆，符合统一真相层约束
- PM 输出的是目标状态，不是执行动作，符合边界约束
- 正式提交统一经 AG 准入校验，符合协作层定位

## 4. 第 0 阶段：研究与现状归档

- 对齐 PM 的真实岗位职责与触发节奏
- 对齐 PM 输入源和记忆读取边界

## 5. 第 1 阶段：设计与契约

- 定义 `strategy` 正式提交最小字段
- 定义 PM revision 的触发来源
- 定义 PM 记忆由 `memory_assets` 托管的边界

## 6. 第 2 阶段：任务分解与迁移路径

- 先固化 Agent 主规格与数据模型
- 再回写 AG、WO、`memory_assets` 与 legacy 文档
- 最后在代码层接入正式提交流程

## 7. 产物清单

- `research.md`
- `data-model.md`
- `quickstart.md`
- `tasks.md`
- `analysis.md`
