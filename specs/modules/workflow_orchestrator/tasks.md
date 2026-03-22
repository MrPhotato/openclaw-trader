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
