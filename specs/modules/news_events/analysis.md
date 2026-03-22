# 一致性分析：News Events

## 结论

- 新主规格已把 `news_events` 收敛到“批次 + 客观事件”边界
- `MEA` 的语义归并与长期记忆没有再写回新闻模块
- `workflow_orchestrator` 只消费客观批次事件

## 仍需后续处理

- 代码层事件名仍需从 `news.synced` 收敛到 `NEWS_BATCH_READY`
- 固定源清单和游标恢复策略仍待后续细化
