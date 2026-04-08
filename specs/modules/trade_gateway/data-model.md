# 数据模型：Trade Gateway

## 1. MarketSnapshotNormalized

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `snapshot_id` | string | 快照 ID |
| `coin` | string | 币种 |
| `product_id` | string | 交易所产品标识 |
| `mark_price` | string | 标记价格 |
| `index_price` | string? | 公允参考价或最接近的指数价 |
| `funding_rate` | string? | 资金费率 |
| `premium` | string? | 溢价 |
| `open_interest` | string? | 未平仓量 |
| `day_notional_volume` | string? | 日名义成交额 |
| `spread_bps` | number? | 最优盘口价差 |
| `trading_status` | string? | 交易状态 |
| `trading_disabled/cancel_only/limit_only/post_only` | boolean | 交易限制标志 |
| `captured_at` | datetime | 采集时间 |

## 2. AccountSnapshot

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `coin` | string | 币种 |
| `total_equity_usd` | string | 总权益 |
| `available_equity_usd` | string | 可用权益 |
| `current_side` | string? | 当前方向 |
| `current_notional_usd` | string? | 当前名义敞口 |
| `current_leverage` | string? | 当前杠杆 |
| `current_quantity` | string? | 当前持仓数量 |
| `entry_price` | string? | 开仓均价 |
| `unrealized_pnl_usd` | string? | 未实现盈亏 |
| `liquidation_price` | string? | 风险价或最接近的清算价 |

## 3. PortfolioSnapshot

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `starting_equity_usd` | string | 起始权益 |
| `realized_pnl_usd` | string | 已实现盈亏 |
| `unrealized_pnl_usd` | string | 未实现盈亏 |
| `total_equity_usd` | string | 总权益 |
| `available_equity_usd` | string | 可用权益 |
| `total_exposure_usd` | string | 总名义暴露 |
| `open_order_hold_usd` | string | 未完成订单占用 |
| `positions[]` | array | 每币结构化仓位快照，带 `position_share_pct_of_exposure_budget`；该字段表示 exposure budget 占比，分母为 `total_equity_usd * max_leverage` |

## 4. ProductMetadataSnapshot

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `coin` | string | 币种 |
| `product_id` | string | 产品标识 |
| `tick_size` | string | 最小价格跳动 |
| `size_increment` | string | 最小数量步进 |
| `min_size` | string? | 最小下单数量 |
| `min_notional` | string | 最小名义金额 |
| `max_leverage` | string? | 产品允许的最大杠杆 |
| `trading_status` | string? | 交易状态 |
| `trading_disabled/cancel_only/limit_only/post_only` | boolean | 交易限制标志 |

## 5. MarketContextNormalized

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `compressed_price_series` | object | 多尺度压缩价格序列，至少覆盖 `15m/1h/4h/24h` |
| `key_levels` | array | 各尺度高低点与关键价位 |
| `breakout_retest_state` | object | 突破/回踩状态 |
| `volatility_state` | object | 波动扩张/收缩/正常状态 |
| `shape_summary` | string | 价格形态摘要 |
| `liquidity.best_bid/best_ask/spread_bps` | fields | 最优盘口与价差 |
| `liquidity.orderbook_depth` | object? | 顶层深度摘要 |

## 6. ExecutionHistorySnapshot

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `recent_orders` | array | 最近订单 |
| `recent_fills` | array | 最近成交 |
| `failure_sources` | array | 最近失败来源 |
| `open_orders[]` | array | 未完成订单的结构化摘要 |

## 7. ExecutionRunRecord

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `decision_id` | string | 对应 RT 决策 ID |
| `strategy_id` | string? | 对应 PM 策略 ID |
| `symbol` | string | 交易对 |
| `action` | string | 本次执行动作 |
| `submitted_at` | datetime | 提交到执行层时间 |
| `finished_at` | datetime? | 本次执行完成时间 |
| `success` | boolean | 是否成功完成 |
| `order_ids` | array[string] | 关联交易所订单 ID |
| `avg_fill_price` | string? | 平均成交价 |
| `filled_size` | string? | 实际成交数量或名义值 |
| `slippage_bps` | number? | 相对决策时基准价的滑点 |
| `failure_reason` | string? | 若失败或异常，记录原因 |

## 8. DataIngestBundle

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `trace_id` | string | 工作流追踪 ID |
| `market` | object | 按币种索引的 `MarketSnapshotNormalized` |
| `accounts` | object | 按币种索引的 `AccountSnapshot` |
| `portfolio` | object | 结构化 `PortfolioSnapshot` |
| `market_context` | object | 按币种索引的 `MarketContextNormalized` |
| `execution_history` | object | 按币种索引的 `ExecutionHistorySnapshot` |
| `product_metadata` | object | 按币种索引的 `ProductMetadataSnapshot` |

## 9. 关系与约束

- `market_data` 负责交易所运行时事实与近端派生上下文，不负责量化训练历史回填
- `PortfolioSnapshot` 不得退回成未结构化 `dict`
- `Risk Trader` 需要的 BBO、spread、深度、未完成订单、失败历史和产品约束，都必须来自本模块结构化资产
- `market_data` 与 `execution` 的实体可共享 `coin/product_id`，但不得共享业务职责
- `ExecutionRunRecord` 是最小运行流水，不等于 RT 的长期记忆
