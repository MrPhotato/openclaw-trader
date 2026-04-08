# 模块规格说明：Policy Risk

**状态**：主真相层已定稿
**对应实现**：`src/openclaw_trader/modules/policy_risk/`  
**来源承接**：`001`、`004`

## 1. 背景与目标

`policy_risk` 是系统唯一的硬风控边界模块。它不保留 `shadow_policy`，也不输出软建议，只负责明确“可不可以承担风险、风险上限是多少、何时必须收缩或退出”。

## 2. 职责

- 产出交易可用性、杠杆和敞口上限
- 维护 `position_risk_state`、`portfolio_risk_state`、`cooldown`、`panic_exit`、`breaker`
- 向策略层和执行层提供不可绕过的硬边界
- 作为 RT 正式执行命令进入 execution 之前的唯一业务检查关口

## 3. 拥有资产

- `TradeAvailability`
- `RiskLimits`
- `PositionRiskState`
- `PortfolioRiskState`
- `GuardDecision`

## 4. 输入

- `quant_intelligence` 的结构化市场事实
- `Trade Gateway.market_data` 提供的账户、持仓和组合事实
- 来自 `memory_assets` 的必要事件记忆引用

## 5. 输出

- 结构化硬风控决策
- `TradeAvailability`
- `RiskLimits`
- `PositionRiskState`
- `PortfolioRiskState`
- `GuardDecision`
- 可供 PM、`Risk Trader` 和 `Trade Gateway.execution` 消费的统一边界

## 6. 直接协作边界

- 向 PM 和 `Risk Trader` 输出硬边界
- 接收 RT 经 `agent_gateway` 校验后的正式执行提交并完成业务检查
- 仅把已通过硬风控的执行命令继续分发到 `Trade Gateway.execution`
- 向 `memory_assets` 提交风控状态变化

## 7. 不负责什么

- 不负责 strategy thesis、建议仓位或 `shadow_policy`
- 不负责新闻分发、Agent 路由和 owner 沟通
- 不负责执行时机选择

## 8. 当前已定

- `max_leverage = 5.0`
- `max_total_exposure_pct = 100.0`
- `max_symbol_position_pct = 66.0`
- `max_order_pct = 33.0`
- `position_risk_state` 阈值为 `observe 0.8% / reduce 1.4% / exit 2.2%`
- `position_risk_state` 统一按单仓自身 trailing peak/trough drawdown 计算，不再按入场价 adverse move 计算
- `portfolio_risk_state` 阈值为 `observe 0.6% / reduce 1.0% / exit 1.8%`
- `portfolio_risk_state` 统一按 `UTC` 当日峰值权益回撤计算
- `cooldown` 仅由 `position_risk_state = exit` 触发，持续单币 `30` 分钟
- `panic_exit` 为账户级灾难刹车，阈值严格读取配置，不替代组合高点回撤刹车
- `breaker` 为当日 `1` 次 `panic_exit` 或 `2` 次 `position_risk_state = exit`
- `breaker` 持续到次日 `UTC 00:00`，支持人工提前解除或人工延长
- 所有 exposure 类百分比边界统一按 `total_equity_usd * max_leverage` 为分母，不按裸权益为分母
- `policy_risk` 只输出硬边界，不输出软建议、不做 approve/reject 审核
- `1h` 市场事实不进入 `policy_risk` 主判断链，主用 `4h / 12h`
- RT 正式执行链中的业务检查统一由 `policy_risk` 承担，execution 不重复检查
- `reduce_only` 表示只允许 `reduce / close / hold / wait`
- `flat_only` 表示只允许 `close / hold / wait`
- `reduce_only / flat_only` 风险锁统一由新的 PM strategy revision 释放，不靠固定时间自动解锁

## 9. 待后续讨论

- 无。当前风险语义和阈值已定稿，后续只剩实现细节与代码收口。
