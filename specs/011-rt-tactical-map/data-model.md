# 数据模型：RT 当班战术地图

## 1. RTTacticalMap（RT 当班战术地图）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `map_id` | string | 地图版本 ID |
| `strategy_key` | string | 当前绑定的 PM 策略版本键 |
| `created_at_utc` | datetime | 初次创建时间 |
| `updated_at_utc` | datetime | 最近更新时间 |
| `map_refresh_reason` | string | 本次刷新原因 |
| `portfolio_posture` | string | 当前组合打法姿态，例如 `build / hold / harvest / de-risk / flat-watch` |
| `desk_focus` | string | 当前交易台最重要的关注点 |
| `risk_bias` | string | 当前风险倾向，例如 `press / balanced / defensive` |
| `coins` | RTTacticalCoinMap[] | 活跃币种的分币种战术地图 |
| `next_review_hint` | string | 下一次最值得检查的条件或时间窗 |

## 2. RTTacticalCoinMap（单币战术地图）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `coin` | string | 币种 |
| `working_posture` | string | 当前该币的打法姿态 |
| `base_case` | string | 当前基本打法摘要 |
| `first_entry_plan` | string | 第一笔怎么打 |
| `preferred_add_condition` | string | 优先加仓条件 |
| `preferred_reduce_condition` | string | 优先减仓条件 |
| `reference_take_profit_condition` | string | 参考止盈条件 |
| `reference_stop_loss_condition` | string | 参考止损条件 |
| `no_trade_zone` | string | 明确不动作区域 |
| `force_pm_recheck_condition` | string | 强制 PM 重评条件 |
| `next_focus` | string | 下轮最该盯的点 |

## 3. TriggerDelta（本次触发增量）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `trigger_reason` | string | 本次唤醒原因 |
| `trigger_severity` | string | 本次触发严重度 |
| `strategy_changed` | boolean | 是否发生策略变化 |
| `risk_brake_changed` | boolean | 是否发生系统风控动作变化 |
| `positions_changed` | boolean | 是否发生仓位变化 |
| `execution_changed` | boolean | 是否有新成交或成交结果变化 |
| `market_structure_changed_coins` | string[] | 结构发生关键变化的币种 |
| `headline_risk_changed` | boolean | 头条风险是否有显著变化 |
| `lock_mode` | string? | 当前风险锁模式 |
| `summary` | string | 面向 RT 的简明增量解释 |

## 4. TacticalMapRefreshReason（地图刷新原因）

| 值 | 含义 |
| --- | --- |
| `pm_revision` | PM 新策略 revision 后刷新 |
| `risk_brake` | 系统风控动作后刷新 |
| `post_trade_refresh` | RT 完成重要执行动作后刷新 |
| `manual_reframe` | RT 判断旧地图失效，自主重构 |
