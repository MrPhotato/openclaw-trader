# Quickstart：Trade Gateway

## 场景 1：读取标准化市场事实

1. 从交易所拉取公共和私有事实
2. 产出 `MarketSnapshotNormalized`、`AccountSnapshot`、`MarketContextNormalized`
3. 将正式资产提交给下游模块和 `memory_assets`

## 场景 2：消费正式执行输入

1. 接收结构化执行输入
2. 生成 `ExecutionPlan`
3. 执行后回填 `ExecutionResult`

## 验收要点

- `Trade Gateway` 不解释策略 thesis
- `market_data` 与 `execution` 分工不混淆
- 执行结果可回放、可追溯
