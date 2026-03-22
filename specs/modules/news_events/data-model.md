# 数据模型：News Events

## 1. NewsDigestEvent

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `news_id` | string | 新闻条目 ID |
| `source` | string | 来源 |
| `title` | string | 标题 |
| `url` | string | 原文链接 |
| `summary` | string? | 简短摘要 |
| `severity` | string | 初始严重度标签 |
| `published_at` | datetime? | 发布时间 |
| `captured_at` | datetime | 抓取时间 |
| `tags` | array | 基础标签 |

## 2. NewsBatch

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `batch_id` | string | 批次 ID |
| `source_window_start` | datetime | 批次开始时间 |
| `source_window_end` | datetime | 批次结束时间 |
| `items` | array[`NewsDigestEvent`] | 批次条目 |
| `dedupe_summary` | object | 去重统计 |

## 3. NewsBatchReadyEvent

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `batch_id` | string | 就绪批次 ID |
| `item_count` | integer | 条目数 |
| `emitted_at` | datetime | 事件时间 |
| `sources` | array[string] | 涉及来源 |

## 4. SourceCursor

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `source` | string | 来源标识 |
| `last_seen_at` | datetime | 最近拉取位置 |
| `last_success_at` | datetime | 最近成功时间 |

## 5. 关系与约束

- `NEWS_BATCH_READY` 只引用批次，不复制整批内容
- `NewsBatch` 必须能被 `MEA` 重复读取
- `dedupe_summary` 只记录轻去重结果，不记录语义归并
