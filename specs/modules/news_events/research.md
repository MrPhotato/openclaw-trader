# 研究记录：News Events

## 决策 1：新闻模块只做到批次，不做到事件真相

- **Decision**：`news_events` 只负责固定源轮询、轻去重、标准化和批次输出
- **Rationale**：语义归并与长期事件真相属于 `MEA + memory_assets`
- **Alternatives considered**：让新闻模块直接维护事件生命周期；结论是会重新混淆新闻和记忆

## 决策 2：客观触发统一为 NEWS_BATCH_READY

- **Decision**：新闻模块对系统只发出 `NEWS_BATCH_READY`
- **Rationale**：这是客观批次就绪事件，不混入后续语义判断
- **Alternatives considered**：继续使用 `news.synced` 或附带提醒字段；结论是不利于新主语义收敛

## 决策 3：只做轻去重

- **Decision**：批次侧只保留标题/链接/时间窗口等轻去重
- **Rationale**：重语义去重应该留给 `MEA`
- **Alternatives considered**：在新闻模块里直接做语义归并；结论是会模糊模块边界
