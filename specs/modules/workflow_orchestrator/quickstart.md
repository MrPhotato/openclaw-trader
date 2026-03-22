# Quickstart：Workflow Orchestrator

## 场景 1：客观唤醒 MEA

1. 接收 `NEWS_BATCH_READY`
2. 触发一次 `MEA` 唤醒
3. 重置基础 `2h` 计时器

## 场景 1.1：固定班次由外部调度器送达

1. OpenClaw `cron` 在固定班次唤醒 `PM` / `RT` / `MEA` / `Chief`
2. `workflow_orchestrator` 记录该次唤醒进入系统生命周期
3. 固定班次之外的复杂调度仍由 `workflow_orchestrator` 继续管理

## 场景 2：记录工作流状态

1. 接收控制命令
2. 产生命令回执
3. 写入 `WorkflowStateRecord`

## 场景 3：收到 PM 正式策略

1. 读取通过 AG 校验的 `strategy` 提交
2. 提取 `scheduled_rechecks[]`
3. 为每条 recheck 注册未来托管任务
4. 触发一次 RT 决策

## 验收要点

- `workflow_orchestrator` 不订阅 `MEA` 结果内容
- `workflow_orchestrator` 不中转 `MEA -> PM` 的协作消息
- 状态、计时器和 recheck 注册都可被 `memory_assets` 收口和回放
- 固定班次可由 OpenClaw `cron` 提供，但 recheck 和事件驱动额外唤醒仍由 `workflow_orchestrator` 负责
