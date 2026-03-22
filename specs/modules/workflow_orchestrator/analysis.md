# 一致性分析：Workflow Orchestrator

## 结论

- 新主规格已把控制平面对 `MEA` 的职责收敛到客观唤醒与正式收口
- `MEA` 协作消息不再由 `workflow_orchestrator` 内容路由
- PM 正式策略进入 WO 后只消费 recheck 元数据，不解释完整策略
- `high` 级事件不再由 `workflow_orchestrator` 托管，转为 `MEA` 直接提醒相关 Agent

## 仍需后续处理

- 代码层仍需把旧的调度和 handler 语义与新状态机名对齐
