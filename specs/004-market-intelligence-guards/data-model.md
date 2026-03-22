# 数据模型：市场智能与风险守卫

## 1. MarketSnapshotNormalized

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `snapshot_id` | string | 快照 ID |
| `coin` | string | 币种 |
| `mark_price` | string | 标记价格 |
| `funding_rate` | string | 资金费率 |
| `premium` | string | 溢价 |
| `open_interest` | string | 未平仓量 |
| `day_notional_volume` | string | 24h 成交额 |
| `captured_at` | datetime | 采样时间 |

## 2. NewsEventMaterialized

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `event_id` | string | 新闻事件 ID |
| `source` | string | 来源 |
| `title` | string | 标题 |
| `severity` | string | 紧急度 |
| `layer` | string | 上下文层 |
| `scope` | string | 影响范围 |
| `published_at` | datetime | 发布时间 |
| `summary` | string | 提炼摘要 |

## 3. MultiHorizonPredictionReady

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `coin` | string | 币种 |
| `h1` | object | `1h` 输出 |
| `h4` | object | `4h` 输出 |
| `h12` | object | `12h` 输出 |
| `regime` | object | regime 判断 |
| `diagnostics` | object | 分歧、校准、质量等诊断 |

## 4. RiskGuardDecisionReady

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `coin` | string | 币种 |
| `trade_availability` | object | 是否允许承担新增风险 |
| `risk_limits` | object | 杠杆与敞口上限 |
| `position_risk_state` | object | `normal/observe/reduce/exit` |
| `diagnostics` | object | 诊断信息 |
