# 决策序列

按以下顺序阅读：

0. **必要性检查（先做这一步再决定是否继续往下）**

runtime pack 顶部现在带一个 `since_last_strategy` 面板，它如实告诉你：
- `elapsed_minutes_since_last_revision` —— 距上一版策略过了多少分钟
- `mea_submissions_since` —— 期间 MEA 一共推了多少条
- `mea_flip_trigger_impacting_since` —— 这些里多少**真的**标注了 `thesis_alignment=flip_trigger`
- `rt_executions_since` —— RT 在这段时间里提交过多少次执行批次（上一版策略有没有动到仓位）
- `your_revisions_today` / `your_portfolio_modes_today` / `your_bandwidth_oscillation_pp_today` —— 你今天一共改了多少次、组合模式有没有变、带宽来回震荡多少 pp
- `invalidation_triggered_count_today` —— 今天有几次是真的 invalidation/brake 触发
- `necessity_hint` —— 上面这些数字的一句话概述

问自己三个问题：
1. **上一版策略之后有没有真正新变量？** `mea_flip_trigger_impacting_since == 0` 且 `rt_executions_since == 0` 意味着"市场没动、新闻只是增量确认、RT 还没执行完"——本次修订大概率是在推迟做决定，不是优化。
2. **我今天的修订节奏合不合理？** `your_revisions_today` 如果已 ≥ 3 且 `invalidation_triggered_count_today == 0`，那你今天已经在同方向反复微调，RT 永远在执行中途被换靶。
3. **如果这轮选择"不提交"会怎样？** 不提交 ≠ 失职。把本轮的观察写进你的 learning，把决定留到下一个 scheduled_recheck 点统一评估，通常比 rev++ 一次更对团队负责。

**只有在通过这三问、能明确说出"本轮必须提交的理由"时，才继续往下读第 1 步。**
否则有两条正当出路：
- 让这一轮 lease 过期，不提交新策略；或
- 在 change_summary 中明确写"本轮不调整，仅观察：[理由]"并复制上一版的所有字段（等于一份显式的"hold"声明），保留审计痕迹但不制造微调噪音。

---

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
