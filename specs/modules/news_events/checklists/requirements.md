# 规格质量检查清单：News Events

**Purpose**：验证新闻模块的职责收敛与 MEA 边界  
**Created**：2026-03-15  
**Feature**：[spec.md](specs/modules/news_events/spec.md)

## Content Quality

- [x] 已明确固定源轮询、轻去重和批次输出
- [x] 已明确 `NEWS_BATCH_READY` 是客观事件
- [x] 已明确不负责语义归并和长期记忆

## Truth Alignment

- [x] 未把普通事件分发写回 `news_events`
- [x] 未把长期记忆写回 `news_events`
