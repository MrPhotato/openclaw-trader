# 规格质量检查清单：Macro & Event Analyst

**Purpose**：验证 MEA 主线工作方式与正式提交边界  
**Created**：2026-03-15  
**Feature**：[spec.md](specs/agents/macro_event_analyst/spec.md)

- [x] 已明确 `2h` 巡检与 `NEWS_BATCH_READY` 唤醒
- [x] 已明确正式结果无 `alert`
- [x] 已明确可直接提醒 `PM`
- [x] 已明确 `high` 级事件需同时直接提醒 `PM` 与 `Risk Trader`
- [x] 已明确不得自写长期记忆
- [x] 已明确 MEA 的复盘 learning 固定写入 `.learnings/macro_event_analyst.md`
