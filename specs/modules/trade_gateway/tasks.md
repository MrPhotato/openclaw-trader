# 任务分解：Trade Gateway

**规格文档**：`specs/modules/trade_gateway/spec.md`

## 第一波：主规格收口

- [ ] T001 固化 `Trade Gateway` 顶层单模块与 `market_data/execution` 双子域边界
- [ ] T002 统一市场事实、账户事实和执行交付实体命名

## 第二波：重点契约

- [ ] T003 定义 `MarketSnapshotNormalized`、`MarketContextNormalized`、`ExecutionResult` contracts
- [ ] T004 记录新增市场上下文字段与下游消费边界

## 第三波：旧文档回写

- [ ] T005 在旧 feature specs 中统一引用新的 `Trade Gateway` 主规格
- [ ] T006 清理旧“双顶层模块”残留表述
