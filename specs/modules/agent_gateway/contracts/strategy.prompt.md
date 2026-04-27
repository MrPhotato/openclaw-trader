# strategy prompt contract

把 `strategy.schema.json` 作为正式提交合同附加到 PM 的正式提交通道中。

要求：

- 只输出符合 schema 的 JSON
- 不输出 markdown 包裹
- 不输出系统字段；正式资产里的 `strategy_id`、`strategy_day_utc`、`generated_at_utc`、`trigger_type` 由系统补齐
- `targets[]` 只表达目标状态与 RT 的执行边界，不表达执行路径
- `targets[]` 必须始终覆盖 `BTC` / `ETH` 两个币；即使某个币当前不做，也要显式标记成 `watch` 或 `disabled`
- 每个 `target` 都要显式填写 `rt_discretion_band_pct`
- 所有持仓/暴露相关百分比统一按 `total_equity_usd * max_leverage` 的 exposure budget 口径表达
- `flip_triggers` 必须写成一句或几句明确条件，表达什么情况下应从当前方向翻到反向，而不是只写泛泛风险提示
- `scheduled_rechecks[]` 的 `reason` 要写成留给未来的一句话
- **`price_rechecks[]` 是 `flip_triggers` 散文的可执行映射（2026-04-27 引入）**：
  - 你写在 `flip_triggers` 里的每条**带具体数值阈值**的条件，都必须在 `price_rechecks` 里有对应的结构化订阅，否则它**永远不会自动触发** —— RT 不会自治执行 flip_triggers，只有你自己被叫醒发新 rev 才会变现。
  - 每个订阅是一次性的：触发后就消耗了；你下次提交策略时若仍想监控同一条件，需要再次声明（或换一个 subscription_id 复发）
  - `subscription_id` 起一个稳定可读的英文 id（如 `plan_a_brent_breach`、`btc_breakdown_77500`），方便你日后在 trigger event 里看到自己写的哪一条触发了
  - `metric` 仅允许这三类 dotted path：
    - `market.market.<COIN>.mark_price`（perp mark）
    - `market.market.<COIN>.index_price`（index）
    - `macro_prices.<symbol>.price`（symbol 取 brent / wti / dxy / us10y_yield_pct 之一）
  - `operator` ∈ {`>=`, `<=`, `>`, `<`}；threshold 是浮点
  - **写散文 `flip_triggers` 时**：保留那些 *没有具体数值的*（结构性、定性的）条件给 RT 当背景；**有数值**的关键阈值同步落进 `price_rechecks`
- **`portfolio_thesis` 是论断数组，不是一段文字（spec 015 FR-001）**：
  - 每条论断必须独立，单句表达
  - 每条必须标 `evidence_type`：
    - `price_action`：来自 Deribit basis、funding、orderbook、市场结构
    - `quant_forecast`：来自 runtime_pack.forecasts 的 1h/4h/12h 方向与置信度
    - `narrative`：来自 Polymarket 概率、新闻叙事、MEA 推理（这是最容易错的一类；给 narrative 标 narrative 比伪装成 price_action 诚实得多）
    - `regime`：来自 runtime_pack.latest_macro_brief.regime_tags 或 pm_directives
    - `mixed`：确实混合了多类证据
  - `evidence_sources[]` 列出具体数据点，不要写"市场结构"这种抽象词
  - 核心论断至少 3 条；当论断 ≥ 2 条时必须覆盖至少 2 种不同的 evidence_type
- **`change_summary` 是对象，不是字符串（spec 015 FR-002）**：
  - `headline`：一句话总结本次变更
  - `evidence_breakdown`：四个百分比加起来必须等于 100；诚实披露你用了多少 narrative
  - `why_no_external_trigger`：仅当你本轮提交没有任何外部触发器 (new MEA event / price breach / quant flip / risk_brake / owner_push) 时填写；系统会检查这段文字的自反性
