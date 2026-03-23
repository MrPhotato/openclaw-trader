# 数据模型：Risk Trader

## 1. ExecutionSubmission

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `decision_id` | string | 本次 RT 正式提交的唯一 ID |
| `strategy_id` | string? | 关联 PM 策略 ID，可选但建议保留 |
| `generated_at_utc` | string | 生成时间 |
| `trigger_type` | string | 触发原因，例如 `scheduled_cycle` / `new_strategy` / `risk_change` / `execution_exception` / `mea_alert` |
| `decisions` | ExecutionDecisionItem[] | 一次短执行批次，可覆盖多个币 |

## 2. ExecutionDecisionItem

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `symbol` | string | 交易对 |
| `action` | string | `open` / `add` / `reduce` / `close` / `flip` / `wait` |
| `direction` | string? | `long` / `short` / `flat`；`wait` 时可为空 |
| `size_pct_of_equity` | number? | 本轮计划处理的 exposure budget 占比，分母为 `total_equity_usd * max_leverage`；`wait` 时可为空 |
| `priority` | integer | 同一批次内的执行优先级 |
| `urgency` | string | `low` / `normal` / `high` |
| `valid_for_minutes` | integer | 本轮判断在多长时间内有效 |
| `reason` | string | 这条动作的简短解释 |
| `reference_take_profit_condition` | string? | 纯文字的参考止盈/退出条件，供下一次 RT cadence 续接思路，不直接生成订单 |

## 3. 关系与约束

- 一次 `ExecutionSubmission` 可以包含多个 symbol 的短执行批次
- RT 只定义“这轮怎么打”，不直接定义交易所订单细节
- `size_pct_of_equity`、`direction` 与 `action` 必须受 PM 的 `target_exposure_band_pct` 和 `rt_discretion_band_pct` 约束
- `size_pct_of_equity` 的百分比口径虽然沿用旧字段名，但语义已统一为 `% of exposure budget`
- RT 不依赖长期记忆；输入默认来自当前 `ExecutionContext`、`market_data`、`policy_risk` 与 `quant_intelligence`
- 对应的最小执行流水由 `Trade Gateway.execution` 记录，不视为 RT 记忆
- RT 的 execution alpha 复盘账只服务 `Chief` 主持的复盘学习，不进入日常执行上下文
