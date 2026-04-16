# 决策序列

按以下顺序阅读：

1. 当前策略与目标差距
- 当前有哪些处于活跃状态
- 自上一版以来有何变化
- 哪些已安排的复查仍未完成

2. 风险边界
- `policy_risk` 硬限制
- 哪些目标实际上已受到约束

3. 事件层
- `MEA` 结构化事件
- 可能推翻 thesis 的直接 MEA 提醒

4. 量化层
- `QI` `1h/4h/12h`
- 使用 `4h/12h` 作为主要结构锚点
- 使用 `1h` 作为辅助参考，而非机械性策略触发器

5. 运行时市场/账户事实
- `Trade Gateway.market_data`
- 权益、敞口、持仓、未成交挂单占用、当前市场背景

6. 带宽自检
- 当前给 RT 的 `target_exposure_band_pct` 和 `rt_discretion_band_pct` 是否足以让 RT 表达 thesis？
- 如果方向正在被验证（QI 确认、关键位突破、MEA 利好），是否应该主动扩大带宽？
- 不要让过窄的带宽成为"隐性保守"——PM 认为自己给了方向，但 RT 实际无法执行。

然后决策：
- portfolio mode
- 总敞口带宽
- 单品种方向
- 明确的 `BTC / ETH` 目标状态，即使部分仅为 `watch` 或 `disabled`
- `target_exposure_band_pct`
- `rt_discretion_band_pct`
- `flip_triggers`
- 带宽是否匹配 thesis 置信度——置信度高时带宽窄是隐性保守

`flip_triggers` 是指那些不仅能推翻当前 thesis、还能证明方向性偏向翻转的具体条件——从做多到做空、从做空到做多、或从主动持仓到平仓/仅减仓。
