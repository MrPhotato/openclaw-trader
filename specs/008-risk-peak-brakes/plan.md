# 实施计划：风控峰值刹车与双触发闭环

**功能分支**：`codex/008-risk-peak-brakes`  
**规格文档**：`specs/008-risk-peak-brakes/spec.md`  
**计划日期**：2026-04-08

## 1. 执行摘要

这次实现分三层推进：
- 在 `policy_risk` 中补齐单仓峰值回撤和组合高点回撤的状态机
- 在 `workflow_orchestrator` 中新增独立的 `risk_brake` 轻量监控器，负责自动风控单和 RT/PM 双触发
- 在 `agent_gateway` runtime pack 中加入最近一次系统风控事件，完成 PM/RT 的后续接棒

## 2. 技术背景（Technical Context）

- **现有系统事实**：RT 条件触发监控器已经存在；PM 固定班次复用 OpenClaw cron；执行链与状态回写链已统一。
- **目标边界**：不新增第二套订单体系，不绕回旧 WO-first runtime push 路径，不修改单笔上限。
- **主要依赖**：`policy_risk`、`workflow_orchestrator`、`agent_gateway`、`trade_gateway.execution`、`state_memory`
- **未知项 / 待确认项**：无，数值、口径和触发顺序已锁定。

## 3. 宪法检查（Constitution Check）

- 所有系统风控动作必须通过现有正式执行链落账，不允许旁路。
- 运行时协作必须复用 OpenClaw 现有 cron/job/session 机制，不新造调度入口。
- 任何自动风控必须显式可配置，并具备幂等/锁释放规则，避免反复自动下单。

## 4. 第 0 阶段：研究与现状归档

- 固化当前 `policy_risk` 的入场价 adverse move 实现与现有 `panic_exit` 语义
- 固化 `rt_trigger` 已有的 `openclaw cron run` 桥接方式
- 固化 `pm-main` 与 `rt-15m` 当前 cron job id 和调度入口

## 5. 第 1 阶段：设计与契约

- 为 `policy_risk` 增加 `PortfolioRiskState`
- 为 `workflow_orchestrator` 增加 `RiskBrakeState` 与 `RiskBrakeEvent`
- 约定 `reduce_only / flat_only` 风险锁的行为与释放条件
- 约定系统风控单 `decision_id` 前缀和 `actor_role=system`
- 约定 RT/PM runtime pack 中的 `latest_risk_brake_event`

## 6. 第 2 阶段：任务分解与迁移路径

- 先更新配置模型与 speckit 文档
- 再实现 `policy_risk` 的新状态口径和执行授权矩阵
- 然后实现 `workflow_orchestrator/risk_brake.py`
- 再把最新风控事件接入 PM / RT runtime pack
- 最后补测试并决定是否启用运行态开关

## 7. 产物清单

- `research.md`
- `data-model.md`
- `quickstart.md`
- `tasks.md`
