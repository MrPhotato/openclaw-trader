# 规格质量检查清单：Workflow Orchestrator

**Purpose**：验证控制平面对 MEA 的职责收敛  
**Created**：2026-03-15  
**Feature**：[spec.md](specs/modules/workflow_orchestrator/spec.md)

- [x] 已明确统一主动入口与生命周期职责
- [x] 已明确 `2h` MEA 计时器和 `NEWS_BATCH_READY` 重置
- [x] 已明确固定班次可由 OpenClaw `cron` 提供
- [x] 已明确 `workflow_orchestrator` 继续保留复杂调度、recheck 和事件驱动额外唤醒
- [x] 已明确不订阅 `MEA` 结果内容
- [x] 未把 Agent 内容路由写回 `workflow_orchestrator`
- [x] 已明确 `high` 级事件不再由 `workflow_orchestrator` 托管跟踪
