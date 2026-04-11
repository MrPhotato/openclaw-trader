# 数据模型：PM

## 1. StrategySubmission

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `portfolio_mode` | string | `normal` / `defensive` / `only_reduce` / `flat` |
| `target_gross_exposure_band_pct` | number[2] | 组合总目标暴露区间 |
| `portfolio_thesis` | string | 组合级解释 |
| `portfolio_invalidation` | string | 组合级失效条件 |
| `flip_triggers` | string | 从当前方向切到反向或从平到反向的明确触发条件 |
| `change_summary` | string | 相对上一版的变化摘要 |
| `targets` | StrategyTarget[] | 每币目标 |
| `scheduled_rechecks` | ScheduledRecheck[] | 未来重看计划 |

说明：
- 以上是 PM authored submission 字段。
- `strategy_id`、`strategy_day_utc`、`generated_at_utc`、`trigger_type` 由系统在正式落库时补齐。
- `target_gross_exposure_band_pct`、`target_exposure_band_pct`、`rt_discretion_band_pct` 的百分比口径统一以 `total_equity_usd * max_leverage` 为分母。

## 2. StrategyTarget

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `symbol` | string | 交易对 |
| `state` | string | `disabled` / `watch` / `active` / `only_reduce` |
| `direction` | string | `long` / `short` / `flat` |
| `target_exposure_band_pct` | number[2] | 目标暴露区间，按 exposure budget 百分比表示 |
| `rt_discretion_band_pct` | number | RT 可围绕该目标额外上下浮动的幅度，单位为 exposure budget 百分点 |
| `priority` | integer | 执行优先级 |

## 3. ScheduledRecheck

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `recheck_at_utc` | string | 未来重看时间 |
| `scope` | string | `portfolio` 或相关 symbol |
| `reason` | string | 留给未来的一句话 |
