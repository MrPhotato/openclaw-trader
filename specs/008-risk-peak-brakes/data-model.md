# 数据模型：风控峰值刹车与双触发闭环

## 1. PositionRiskState（单仓风险状态）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `state` | string | `normal / observe / reduce / exit` |
| `reasons` | string[] | 触发该状态的原因 |
| `thresholds` | object | 单仓观察/减仓/退出阈值 |
| `drawdown_pct` | float | 当前单仓相对峰值/谷值的回撤 |
| `reference_mode` | string | `peak` 或 `trough` |
| `reference_price` | string? | 当前 trailing 参考价 |

## 2. PortfolioRiskState（组合风险状态）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `state` | string | `normal / observe / reduce / exit` |
| `reasons` | string[] | 触发该状态的原因 |
| `thresholds` | object | 组合高点观察/减仓/退出阈值 |
| `drawdown_pct` | float | 当前账户相对 UTC 当日峰值的回撤 |
| `day_peak_equity_usd` | string | 当日峰值权益 |
| `day_utc` | string | 峰值归属日 |

## 3. RiskBrakeState（风控刹车状态）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `last_scan_at_utc` | datetime? | 最近一次轻量扫描时间 |
| `portfolio_day_utc` | string | 当前峰值所属 UTC 日期 |
| `portfolio_day_peak_equity_usd` | string | 当前保存的当日峰值权益 |
| `position_references_by_coin` | object | 每币 trailing peak/trough 参考价与模式 |
| `portfolio_lock_mode` | string? | `reduce_only / flat_only / null` |
| `portfolio_lock_strategy_key` | string? | 当前组合风险锁绑定的 strategy key |
| `position_lock_mode_by_coin` | object | 每币风险锁 |
| `position_lock_strategy_key_by_coin` | object | 每币风险锁绑定的 strategy key |
| `last_portfolio_state` | string | 最近已处理的组合风险状态 |
| `last_position_state_by_coin` | object | 最近已处理的单仓风险状态 |

## 4. RiskBrakeEvent（风控刹车事件）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `event_id` | string | 风控事件 ID |
| `detected_at_utc` | datetime | 触发检测时间 |
| `scope` | string | `position` 或 `portfolio` |
| `state` | string | `observe / reduce / exit` |
| `coins` | string[] | 影响币种 |
| `risk_lock_mode` | string? | `reduce_only / flat_only / null` |
| `metrics` | object | drawdown、阈值、峰值权益/参考价等指标 |
| `system_decision_ids` | string[] | 系统风控单 decision_id 列表 |
| `execution_result_ids` | string[] | 系统风控单执行结果资产 ID |
| `rt_dispatched` | boolean | 是否已成功触发 RT |
| `pm_dispatched` | boolean | 是否已成功触发 PM |
| `rt_skip_reason` | string? | RT 唤醒跳过原因 |
| `pm_skip_reason` | string? | PM 唤醒跳过原因 |

