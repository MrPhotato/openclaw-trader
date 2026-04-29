# 正式输出

提交前，请打开并严格遵循此 schema：
- `specs/modules/agent_gateway/contracts/strategy.schema.json`

提示词合约参考：
- `specs/modules/agent_gateway/contracts/strategy.prompt.md`

重要字段（每次都必须考虑）：
- `portfolio_mode`
- `target_gross_exposure_band_pct`
- `band_confidence_tier` —— `"standard"`（默认，band 上限 15%）或 `"high"`（band 上限 30%，需配 `band_confidence_evidence` ≥ 30 字 + 当前 ladder=normal）
- `band_confidence_evidence` —— 仅在 `tier="high"` 时必填的一句话证据（说明 flip_trigger 全确认 / regime 已转向）
- `portfolio_thesis` ——**结构化数组**（spec 015 FR-001）；每个论断带 `statement`/`evidence_type`/`evidence_sources`
- `portfolio_invalidation`
- `flip_triggers`
- `change_summary` ——**结构化对象**（spec 015 FR-002）；含 `headline`/`evidence_breakdown`/`why_no_external_trigger?`
- `targets[]`
- `target_exposure_band_pct`
- `rt_discretion_band_pct`
- `scheduled_rechecks[]`
- **`price_rechecks[]` —— 不是可选项**。`flip_triggers` 散文里每写一个带 `> / < / >= / <=` + 数值的硬阈值，`price_rechecks[]` 必须有一条对应的结构化订阅，否则 submit_gate 会以 `unmonitored_flip_thresholds` 拒绝。每条订阅必须包含：`subscription_id`（你起的稳定英文 id）、`metric`（白名单 metric path）、`operator`（**严格只能是 `">="` / `"<="` / `">"` / `"<"` 这四个字面量；不能写 `"gt"` / `"lt"` / `"ge"` / `"le"`**）、`threshold`（数字）、`scope`、`reason`。详见 [price-rechecks-authoring.md](price-rechecks-authoring.md)

规则：
- 正式提交必须是且仅是一个 JSON 对象。
- 保留运行时包中的 `input_id`，并在提交桥接调用时一并发送。
- 仅输出 JSON。不要输出 markdown 围栏、注释、要点列表、标题或尾部文本。
- 如需思考或解释，在正式提交步骤之前完成，而非在提交内容本身中。
- 即使判断未变，仍需发出一份新的策略提交。
- 不要添加执行战术，如订单类型、订单数量或入场路径。
- `flip_triggers` 是一个专用必填字段。用它来阐述什么具体条件能够证明方向性偏向的翻转——从做多到做空、从做空到做多、或从主动持仓到平仓/仅减仓。
- `targets` 必须恰好包含 2 个条目，且必须始终覆盖 `BTC` 和 `ETH`。
- 如果某币种不活跃，仍需显式包含，设置 `state = watch` 或 `disabled` 并标记平仓方向。不要省略符号。
- 将所有敞口百分比视为 `占敞口预算的百分比`，其中敞口预算 = `total_equity_usd * max_leverage`。
- 在此内部约定下，归一化总敞口和归一化单品种敞口不应超过 `100%`。
- 如果你描述当前敞口大于 `100%`，你几乎可以确定使用了错误的分母（`原始名义值 / 权益`），而非内部分母（`权益 * 最大杠杆`）。
- 在行文中描述当前总敞口或当前持仓份额时，优先使用运行时包中已有的归一化值。不要从原始的 `total_exposure_usd / total_equity_usd` 重新计算。
- 不要输出 `strategy_id`、`strategy_day_utc`、`generated_at_utc`、`trigger_type` 或任何来源引用字段。系统会在后续自动添加。
- 不要在普通策略提交中添加 `speaker_role`。

提交桥接：

```bash
curl -s -X POST http://127.0.0.1:8788/api/agent/submit/strategy \
  -H "Content-Type: application/json" \
  -d '{
    "input_id": "input_from_pull_pack",
    "portfolio_mode": "defensive",
    "target_gross_exposure_band_pct": [0, 15],
    "portfolio_thesis": [
      {
        "statement": "BTC 4h 结构还在震荡，突破未确认。",
        "evidence_type": "price_action",
        "evidence_sources": ["BTC 4h range $72.8K-$75.1K 连续 6 根", "12h 高点未刷新"]
      },
      {
        "statement": "quant 1h 短期 direction=long 但 4h/12h 中性，不构成加仓信号。",
        "evidence_type": "quant_forecast",
        "evidence_sources": ["quant BTC:1h dir=long p=0.54", "BTC:4h dir=flat", "BTC:12h dir=flat"]
      },
      {
        "statement": "Chief brief 把 regime 定为 risk_off_with_crypto_headwind，要求窄 band。",
        "evidence_type": "regime",
        "evidence_sources": ["latest_macro_brief.regime_tags.regime_summary"]
      }
    ],
    "portfolio_invalidation": "出现干净的 4h 放量突破，或政策/风控边界变化推翻防守立场。",
    "flip_triggers": "若 BTC 失守高时间框架突破位且 4h/12h 结构同步转空，或宏观冲击明确将制度切换到 risk-off，则从谨慎做多偏向转为防御做空偏向。",
    "change_summary": {
      "headline": "维持防守姿态，将活跃风险收窄至 BTC，ETH 保持观望。",
      "evidence_breakdown": {
        "price_action_pct": 40,
        "quant_forecast_pct": 25,
        "narrative_pct": 5,
        "regime_pct": 30
      },
      "why_no_external_trigger": null
    },
    "targets": [
      {
        "symbol": "BTC",
        "state": "active",
        "direction": "long",
        "target_exposure_band_pct": [0, 10],
        "rt_discretion_band_pct": 5,
        "priority": 1
      },
      {
        "symbol": "ETH",
        "state": "watch",
        "direction": "flat",
        "target_exposure_band_pct": [0, 5],
        "rt_discretion_band_pct": 5,
        "priority": 2
      }
    ],
    "scheduled_rechecks": [
      {
        "recheck_at_utc": "2026-03-22T09:00:00Z",
        "scope": "portfolio",
        "reason": "下一个主要日内结构更新后重新评估。"
      }
    ],
    "price_rechecks": [
      {
        "subscription_id": "btc_breakdown_75k",
        "metric": "market.market.BTC.mark_price",
        "operator": "<",
        "threshold": 75000.0,
        "scope": "portfolio",
        "reason": "BTC 跌破 75K 触发升级 short 至 15% 的预案"
      },
      {
        "subscription_id": "brent_breakout_112",
        "metric": "macro_prices.brent.price",
        "operator": ">=",
        "threshold": 112.0,
        "scope": "portfolio",
        "reason": "Brent 突破 112 + BTC <75K 双确认 → 升级 short"
      }
    ]
  }'
```

**关于 `band_confidence_tier="high"` 的提交形态**（仅在你判定为高把握、且当前 `decision_context.band_tier_eligibility.high_eligible == true` 时使用）：

```jsonc
{
  "input_id": "input_from_pull_pack",
  "portfolio_mode": "defensive",
  "target_gross_exposure_band_pct": [0, 25],
  "band_confidence_tier": "high",
  "band_confidence_evidence": "Flip trigger 全确认: BTC 4h 收盘 < 75000 + Brent 外部报价 > 112 持续 12h + DXY 上行突破 99，三条件同时验证，regime 已确认转向 risk_off。",
  // ... portfolio_thesis / portfolio_invalidation / flip_triggers / change_summary / targets / scheduled_rechecks / price_rechecks 同上
}
```

`high` 档的硬约束（gate 校验，违反即拒）：
- `band_upper` ≤ 30%（超过 30 必拒）
- `band_confidence_evidence` ≥ 30 字（boilerplate 不算；retro 会审计）
- 当前 `risk_brake_state.portfolio_state_ladder_high == "normal"`（`observe`/`reduce`/`exit` 任一在烧均拒）

这三条任意一条不满足，submit_gate 返回 `error_kind: "band_tier_violation"`。

API 兼容性说明：
- `submit/strategy` 接受两种格式：
  - 扁平提交：`{"input_id":"...","portfolio_mode":"...","..."}`
  - 包装提交：`{"input_id":"...","payload":{...strategy fields...}}`
- 推荐使用扁平提交，因为更简洁、更易于理解。

常见映射提醒：
- `portfolio_thesis`，不是 `thesis`
- `portfolio_invalidation`，不是 `invalidation`
- `flip_triggers`，不是 `regime_switch_triggers`
- `change_summary`，不是 `summary`
- `input_id` 必须原样从拉取桥接返回的值中携带回来
- `price_rechecks[]` 字段精确叫这个名，不是 `price_recheck` / `rechecks` / `subscriptions`
- `price_rechecks[].subscription_id`（不是 `id` / `label` / `name` / `subscription`）
- `price_rechecks[].operator` 严格用 `">="` / `"<="` / `">"` / `"<"`；**禁止** `"gt"` / `"lt"` / `"ge"` / `"le"` / `"<="` 之外的任何变体
- `price_rechecks[].metric` 必须命中白名单：`market.market.<COIN>.mark_price` / `market.market.<COIN>.index_price` / `macro_prices.<sym>.price`（`<sym>` ∈ `brent`/`wti`/`dxy`/`us10y_yield_pct`）
- `band_confidence_tier` 严格用 `"standard"` / `"high"`；写 `"normal"` / `"aggressive"` / `"max"` 都会被 schema 拒
