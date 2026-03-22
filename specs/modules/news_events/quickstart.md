# Quickstart：News Events

## 场景 1：固定源轮询

1. 按 `5` 分钟周期拉取固定源
2. 生成 `NewsDigestEvent`
3. 按批次写出 `NewsBatch`

## 场景 2：发出批次就绪事件

1. 批次完成后发出 `NEWS_BATCH_READY`
2. 由 `workflow_orchestrator` 负责后续客观唤醒

## 验收要点

- `news_events` 不做语义归并
- `news_events` 不做普通事件分发
- `NEWS_BATCH_READY` 只表达“批次就绪”
