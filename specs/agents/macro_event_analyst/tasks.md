# 任务分解：Macro & Event Analyst

**规格文档**：`specs/agents/macro_event_analyst/spec.md`

## 第一波：主规格收口

- [ ] T001 固化 `2h` 巡检 + `NEWS_BATCH_READY` 唤醒工作模式
- [ ] T002 固化正式提交仅保留结构化事件列表且无 `alert`

## 第二波：重点契约

- [ ] T003 定义 `MacroEventSubmission` formal contract
- [ ] T004 明确 `high` 级事件直接提醒 `PM` 与 `RT` 的边界与禁止事项
- [ ] T005 明确记忆读取只来自 `memory_assets` 投影

## 第三波：迁移对齐

- [ ] T006 在旧 `006/007` 和总览文档中统一迁移说明
