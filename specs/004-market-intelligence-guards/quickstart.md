# Quickstart：如何使用 004 输出

## 1. 下游模块只消费结构化输出

- `005` 读取 `MarketSnapshotNormalized`、`MultiHorizonPredictionReady` 和 `ShadowPolicyReady`
- `006` 读取新闻摘要和量化判断，不直接读原始 RSS 或原始特征
- `007` 读取风险守卫和新闻事件形成通知与回放素材

## 2. 不允许的接入方式

- 不允许策略模块直接访问原始行情源
- 不允许 Agent 网关直接读取模型 artifact 或原始新闻源
- 不允许执行模块自行重新解释 `1h/4h/12h`
