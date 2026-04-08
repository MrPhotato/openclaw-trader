# 任务分解：Workflow Orchestrator

**规格文档**：`specs/modules/workflow_orchestrator/spec.md`

## 第一波：主规格收口

- [ ] T001 固化统一主动入口、显式状态机和命令幂等语义
- [ ] T002 固化 `MEA` 的 `2h` 计时器与 `NEWS_BATCH_READY` 重置规则

## 第二波：重点契约

- [ ] T003 定义控制命令、状态记录和 `MEA` 计时器 contracts
- [ ] T004 定义 PM 正式策略里的 recheck 元数据消费规则与 RT 触发规则

## 第三波：迁移对齐

- [ ] T006 在旧 `003` 和总览文档中统一迁移说明
- [ ] T007 清理 `MEA alert -> WO` 与 `WO` 订阅 `MEA` 结果内容的旧表述

## 第四波：RT 条件触发调度

- [ ] T008 新增 `workflow_orchestrator/rt_trigger.py`，实现非 LLM 轻量扫描、触发判定和冷却状态维护
- [ ] T009 在 `WorkflowOrchestratorService` 中通过 `dispatch.yaml: rt_event_trigger_enabled` 挂载 `RTTriggerMonitor`，默认关闭
- [ ] T010 通过 `openclaw cron list --json` 检查 RT job 是否运行中，并通过 `openclaw cron run <rt_job_id>` 只入队标准 RT job
- [ ] T011 将 `rt_trigger_state` 与 `rt_trigger_event` 写入 `memory_assets`
- [ ] T012 在 RT runtime pack 中增加 `latest_rt_trigger_event`
- [ ] T013 增加 PM strategy update、MEA high/critical event、market structure change、exposure drift、execution follow-up、heartbeat、cooldown 和 cron-running 测试
- [ ] T014 明确旧 `rt-15m` cron job 不由代码禁用，由用户在切换时手动禁用其固定定时
