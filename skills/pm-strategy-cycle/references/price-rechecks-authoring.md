# price_rechecks 写法指南

`price_rechecks[]` 是 `flip_triggers` 散文里**每条带数值阈值的条件**对应的可执行结构化订阅。 PriceRecheckMonitor 每 ~30s 评估一次，触发时叫醒 PM 自己起床发新 rev——这是 `flip_triggers` 散文条款唯一变现的路径。

## 必要性

- RT **不会自治执行 flip_triggers**。RT 只在 PM 当前 active band 内操作；散文里写"Brent>108 → short 10-12%"这种条件，RT 不会读、不会监控、不会执行。
- PM 的其它唤醒路径都是被动的：scheduled_recheck（时间）、max_silence_since（12h 兜底）、agent_message（RT/MEA push）、risk_brake（系统）。**没有任何路径会监控 PM 自己写下的价格条件**。
- 所以你写"Brent>108 → 翻 short" 但不写对应 `price_rechecks` 订阅 = **永远不会自动触发**，市场冲到 110 你还没醒。

## 字段

```json
{
  "subscription_id": "plan_a_brent_breach",
  "metric": "macro_prices.brent.price",
  "operator": ">=",
  "threshold": 108.0,
  "scope": "portfolio",
  "reason": "Brent breakout — evaluate plan A short flip"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `subscription_id` | string | 你起的稳定可读英文 id；触发后 trigger event 里你能直接看见这个 id 来定位是哪条订阅炸了 |
| `metric` | string (whitelist) | 仅允许下面这三类 dotted path |
| `operator` | enum | `>=` / `<=` / `>` / `<` |
| `threshold` | number | 浮点阈值 |
| `scope` | string | 通常 `"portfolio"`；与 scheduled_rechecks 同语义 |
| `reason` | string | 你写给未来自己的一句话："为啥这个条件值得叫醒我" |

## metric 白名单

只允许下面三类路径（其它路径会被 monitor 静默拒绝）：

| 路径 | 含义 | 刷新 |
|---|---|---|
| `market.market.<COIN>.mark_price` | perp mark 价（COIN ∈ BTC/ETH/...） | bridge 每 ~30s 刷新 |
| `market.market.<COIN>.index_price` | 指数价（与 mark 略有差） | bridge 每 ~30s 刷新 |
| `macro_prices.<symbol>.price` | 宏观资产；symbol ∈ `brent` / `wti` / `dxy` / `us10y_yield_pct` | yfinance，30s 内刷新一次 |

**没有的路径**: 4h 收盘价、basis、funding rate、forecasts、news 计数。这些写在 flip_triggers 散文里给 RT/Chief 当背景，但**机器层面 monitor 看不见**——也就不会自动触发。

## 写法约束 / 实操

1. **flip_triggers 散文里每写一个具体数值阈值，price_rechecks 数组里就要有一条对应**。例外：路径不在白名单里的（比如 4h 收盘 / 基差），只能等下次 PM 起床手动检查。
2. **subscription 是一次性的**：一旦触发即消耗（per (strategy_id, subscription_id) dedup）。下次提交 strategy 时若仍想守这条，必须重新声明，或者用新 `subscription_id`。
3. **每个订阅触发后 PM 会被叫醒**——你会收到一条 wake message，`latest_pm_trigger_event.trigger_type == "price_recheck"`，里面 `fired_subscriptions[]` 列出了所有同时触发的订阅 + observed value + threshold。直接用这个数据决定下一步。
4. **同一秒多条订阅同时满足**：合并成 1 条 wake message（global_cooldown 60s 防止刷屏）。
5. **不要塞太多噪音订阅**：每条订阅炸都会叫醒 PM 整个 turn。建议每个 strategy 不超过 3-5 条订阅，集中在你 thesis 的关键决策面。
6. **触发后**：你提交新 rev 时如果还想保持监控同一条件（比如阈值要紧一档），用新 `subscription_id` 复发；如果条件已经在 thesis 里 absorbed，删掉这条，写新的。

## 示例

```json
"flip_triggers": "若 Brent 周度站上 108 且 BTC 4h 收盘破 78k → 切 plan A short 10-12%；若 BTC mark 失守 77500 → 立即降级 only_reduce。",
"price_rechecks": [
  {
    "subscription_id": "plan_a_brent_breach",
    "metric": "macro_prices.brent.price",
    "operator": ">=",
    "threshold": 108.0,
    "scope": "portfolio",
    "reason": "Brent breakout 是 plan A 的核心引信；触发后用 4h 收盘 + 基差再确认"
  },
  {
    "subscription_id": "btc_breakdown_guard",
    "metric": "market.market.BTC.mark_price",
    "operator": "<=",
    "threshold": 77500.0,
    "scope": "portfolio",
    "reason": "BTC 失守 77500 是结构性破位；立即考虑降级到 only_reduce"
  }
]
```

注意：上面散文还提到 "BTC 4h 收盘破 78k" 这条**没有进 price_rechecks**——因为 4h 收盘价不在白名单里。这条只能靠 scheduled_recheck（时间班次）来兜底检查。

## 反模式

- ❌ 散文里写"Brent>108 → short"但 price_rechecks 数组留空：永远不会触发
- ❌ subscription_id 用 random hash：每次复发都看不出是同一个意图，自己看 trigger event 时迷失
- ❌ 写 10+ 个订阅每个 0.5% 间隔：一个真正的趋势会连续触发几条，PM 被叫醒频率失控
- ❌ 用 `metric: "market.market.BTC.day_price_change_pct"`：路径不在白名单，monitor 静默拒绝（这条字段路径甚至可能不存在）
