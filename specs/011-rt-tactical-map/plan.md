# 实施计划：RT 当班战术地图

**功能分支**：`codex/011-rt-tactical-map`  
**规格文档**：`specs/011-rt-tactical-map/spec.md`  
**计划日期**：2026-04-09

## 1. 执行摘要

这次实现分三层推进：
- 在 `memory_assets` 中增加 RT 专属的 `standing_tactical_map`
  中文：当班战术地图
- 在 `agent_gateway pull/rt` 中增加 `trigger_delta`
  中文：本次触发增量
  和 `standing_tactical_map` 视图
- 在 RT 提示链中把默认工作流收口为“增量 -> 地图 -> 风险锁 -> 按需下钻”，让 RT 更像持续维护交易地图的交易员，而不是重复分析器

## 2. 技术背景（Technical Context）

- **现有系统事实**：RT 已通过 `workflow_orchestrator -> openclaw cron run` 实现条件触发与 heartbeat 兜底；`pull/rt` 已有 `rt_decision_digest`、`latest_rt_trigger_event`、`latest_risk_brake_event`。
- **目标边界**：不改 RT 的标准自动入口，不把机器事件改成写入 RT `main` 会话，不替 RT 自动生成主观战术结论。
- **主要依赖**：`memory_assets`、`agent_gateway`、`workflow_orchestrator`、RT skill / workspace 文档。
- **未知项 / 待确认项**：第一版不做单独 UI，不做人工编辑器；地图的正式持久化入口优先沿用现有 RT 提交流程中的附加更新，而不是引入新的人机接口。

## 3. 宪法检查（Constitution Check）

- RT 的持续战术地图必须通过主真相层资产保存，不能仅依赖 session transcript。
- 自动调度仍需复用 OpenClaw 现有 cron/job 机制，不新造一套机器入口。
- 服务层只能提供更好的长期记忆与增量输入，不应代替 RT 做战术主观判断。

## 4. 第 0 阶段：研究与现状归档

- 归档 RT 当前真实输入链：`rt_decision_digest + latest_rt_trigger_event + latest_risk_brake_event + 原始 drill-down 数据`
- 归档 RT 当前慢的原因：单轮重读稳定文档、重复拆包、没有持续战术地图
- 锁定与真实 trader 工作方式一致的目标：先有战术地图，再只对偏离和触发做判断

## 5. 第 1 阶段：设计与契约

- 为 `memory_assets` 增加 `RTTacticalMap`
  中文：RT 当班战术地图
- 为 `pull/rt` 增加 `TriggerDelta`
  中文：本次触发增量
- 约定地图刷新时机、地图所有权和地图与 `strategy_key / lock_mode` 的绑定方式
- 约定 RT 默认读取顺序和下钻边界
- 补最小 contract，固定 `standing_tactical_map` 与 `trigger_delta` 的返回形状

## 6. 第 2 阶段：任务分解与迁移路径

- 先在 spec 中固化地图字段和刷新规则
- 再实现 `memory_assets` 资产与 `agent_gateway pull/rt` 聚合逻辑
- 再更新 RT skill / runtime-inputs / workspace AGENTS
- 最后补回归测试，验证地图、增量和既有 trigger/risk brake 能共存

## 7. 产物清单

- `research.md`
- `data-model.md`
- `contracts/`
- `quickstart.md`
- `tasks.md`
