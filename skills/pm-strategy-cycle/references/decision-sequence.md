# 决策序列

按以下顺序阅读：

0.a. **决策语境（`decision_context` — 打开 runtime pack 第一眼必读，spec 015 FR-007）**

runtime pack 顶层有一个 `decision_context` 块：
- `regime_summary`：来自 Chief `latest_macro_brief.regime_tags.regime_summary`（可能是 `unknown_brief_missing` / `unknown_brief_stale`）
- `price_snapshot`：`{BTC: {mark, change_pct_24h}, ETH: {mark, change_pct_24h}}`
- `last_thesis_evidence_breakdown`：上一版策略的 `change_summary.evidence_breakdown`（`null` 表示冷启动或旧版本未记录）
- `thesis_price_alignment_flag`：`aligned` / `diverged` / `unknown`——把上一版主方向与 BTC 24h 变动做对比
- `chief_regime_confidence`：`ok` / `low`——连续 3 份 brief 被证伪会降到 `low`

硬约束：
- 如果 `thesis_price_alignment_flag == "diverged"`，**本次 `change_summary.headline` 或 `portfolio_thesis` 必须显式回应**"上一版为什么没对"。submit_gate 不机械校验文本，但 retro 会在次日审阅；不回应会进 learning_directive。
- 如果 `regime_summary == "unknown_brief_missing"` 或 `"unknown_brief_stale"`，**默认保守**：不扩 band、不切换 `portfolio_mode`。在 `change_summary.headline` 里写明"brief 缺失/过期，维持保守"。
- 如果 `chief_regime_confidence == "low"`，把 `latest_macro_brief.pm_directives` 当作次要参考（最近几次 Chief 看错了 regime），以 PM 自己的结构判断为主。

0.b. **宏观 regime（`latest_macro_brief`）**

如果 `decision_context.regime_summary` 不是 `unknown_*`，完整读 `latest_macro_brief.brief.regime_tags` 和 `pm_directives`。PM skill 对 brief 有硬约束（spec 014）：
- `portfolio_thesis` 中至少一条论断必须引用 `regime_tags` 或 `pm_directives`
- 偏离 brief 时必须在 `change_summary.headline` 中显式论证偏离原因
- `latest_macro_brief.missing` 或 `stale`→保守姿态，不扩 band、不切换 `portfolio_mode`

0.c. **必要性检查（先做这一步再决定是否继续往下）**

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

7. **结构化 thesis 与证据披露（spec 015 FR-001/FR-002）**

`portfolio_thesis` 不再是一段自由文字，而是一个论断数组（≥1 项，建议 ≥3 项）。每条：
- `statement`：一句独立论断
- `evidence_type`：`price_action` / `quant_forecast` / `narrative` / `regime` / `mixed`
- `evidence_sources`：具体数据点（例如 `"Deribit BTC 3M basis 5.2%"`）

当论断 ≥ 2 条时必须覆盖至少 2 种不同的 `evidence_type`，否则 schema 拒绝。

`change_summary` 是对象：
- `headline`：一句话总结本次变更
- `evidence_breakdown`：四项 `pct` 之和严格等于 100；诚实披露 narrative 占比是防止"叙事驱动"偏差的核心纪律
- `why_no_external_trigger`：**只在 submit-gate 认为本次修订无外部触发器时填**。submit-gate 会检查是否有：
  - 新 MEA 事件（`news_events` 中在上一版 strategy 之后的新 event_id）
  - 价格突破（BTC/ETH mark 自上一版起 |move| > 1.5%）
  - 量化翻转（任一 horizon 的 direction 翻转）
  - risk_brake（新的 `risk_brake_event`）
  - owner push（`latest_pm_trigger_event.wake_source in {manual, owner_push}`）
  - 都未命中 → 本次修订会被标 `internal_reasoning_only=true`，`why_no_external_trigger` 必填；缺失会被拒为 `hesitation_unjustified`
- `internal_reasoning_only=true` 的修订**不触发 owner 通知、不 sessions_send 给 RT**，但会正常入库；RT 下次 pull 会看到标签，按低权重处理

8. **提交**

按 [formal-output.md](formal-output.md) 输出结构化 JSON。
