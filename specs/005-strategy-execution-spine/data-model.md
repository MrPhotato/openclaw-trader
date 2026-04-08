# 数据模型：策略与执行主脊梁

## 1. StrategyIntent

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `strategy_version` | string | 策略版本 |
| `change_reason` | string | 变更原因 |
| `targets` | array | 目标仓位集合 |
| `thesis` | string | 核心判断 |
| `invalidation` | string | 失效条件 |
| `scheduled_rechecks` | array | 复查安排 |

## 2. ExecutionContext

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `context_id` | string | 执行上下文 ID |
| `strategy_version` | string | 来源策略版本 |
| `coin` | string | 币种 |
| `product_id` | string | 交易标的 |
| `target_bias` | string | 目标方向 |
| `target_position_pct_of_exposure_budget` | number | 目标仓位占 exposure budget 的百分比 |
| `max_position_pct_of_exposure_budget` | number | 该币允许的 exposure budget 上限 |
| `rationale` | string | 目标仓位理由 |
| `market_snapshot` | object | 市场事实快照 |
| `account_snapshot` | object | 账户事实快照 |
| `risk_limits` | object | 硬风控边界 |
| `position_risk_state` | object | 持仓风险状态 |
| `forecast_snapshot` | object | 量化事实快照 |
| `diagnostics` | object | 附加诊断 |

## 3. ExecutionDecision

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `decision_id` | string | 执行决策 ID |
| `context_id` | string | 来源执行上下文 |
| `strategy_version` | string | 来源策略版本 |
| `product_id` | string | 交易标的 |
| `coin` | string | 币种 |
| `action` | string | `open` / `add` / `reduce` / `close` / `flip` / `wait` |
| `side` | string | long / short |
| `notional_usd` | string | 名义价值，可为空 |
| `leverage` | string | 杠杆，可为空 |
| `reason` | string | 决策理由 |

## 4. ExecutionPlan

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `plan_id` | string | 执行计划 ID |
| `decision_id` | string | 来源执行决策 |
| `action` | string | `open` / `add` / `reduce` / `close` / `flip` / `wait` |
| `side` | string | long / short |
| `margin_usd` | string | 保证金 |
| `notional_usd` | string | 名义价值 |
| `leverage` | string | 杠杆 |

## 5. ExecutionResult

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `plan_id` | string | 执行计划 ID |
| `success` | boolean | 是否成功 |
| `exchange_order_id` | string | 交易所订单 ID |
| `message` | string | 结果说明 |
| `fills` | array | 成交回报 |
| `executed_at` | datetime | 执行时间 |
