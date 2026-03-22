# 任务分解：News Events

**规格文档**：`specs/modules/news_events/spec.md`

## 第一波：主规格收口

- [ ] T001 固化固定源、轻去重、批次和 `NEWS_BATCH_READY` 边界
- [ ] T002 统一 `NewsDigestEvent`、`NewsBatch`、`NewsBatchReadyEvent` 命名

## 第二波：重点契约

- [ ] T003 定义新闻批次和批次就绪 contracts
- [ ] T004 记录去重窗口、来源游标和恢复边界

## 第三波：迁移对齐

- [ ] T005 将旧 `news.synced` 语义迁移到 `NEWS_BATCH_READY`
- [ ] T006 在旧 feature specs 中统一引用新的新闻模块主规格
