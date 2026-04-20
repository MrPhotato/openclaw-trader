# Chief 日频宏观 Brief 工作流（spec 014）

当 runtime pack 的 `task_kind` 是 `macro_brief` 时执行此流程。这是**前瞻性** regime framing，不是 retro。

## 职责
- 拉取 `pull_chief_macro_brief_pack`（不要走 `pull_chief_retro_pack`，两者 pack 内容不同）。
- 读 macro_prices、news_events、prior brief，用 `digital-oracle` 补足期限结构、CFTC、Treasury、Fed 概率等前瞻性信号。
- 合成一份 regime 判断：**市场现在在定价什么、为什么、下一步看什么**。
- 对上一份 brief 做 `prior_brief_review` 自评（validated / partially_validated / falsified / no_prior）。
- 提交 `submit/macro-brief`。系统写入 `macro_brief` 资产，下一次 PM/RT/MEA 拉 runtime pack 就能看到。
- **不**触发 retro、**不**发 owner summary、**不**写 learning_directives。

## 拉取 pack

```bash
curl -s -X POST http://127.0.0.1:8788/api/agent/pull/chief-macro-brief \
  -H "Content-Type: application/json" \
  -d '{"trigger_type": "daily_macro_brief"}' \
  | tee /tmp/chief_macro_brief_pack.json
```

pack 顶层字段：
- `input_id`：提交时原样带回
- `task_kind: "macro_brief"`（提交 gate 会强校验）
- `payload.macro_brief_pack.macro_prices`：Brent/WTI/DXY/US10Y/F&G/ETF 活跃度（runtime_pack 的权威来源；不要自己 web_fetch 这些价格）
- `payload.macro_brief_pack.news_events`：MEA 最近的结构化事件
- `payload.macro_brief_pack.forecasts`：量化 1h/4h/12h direction/uncertainty
- `payload.macro_brief_pack.previous_strategy`：PM 上一版策略（看它依赖的假设）
- `payload.macro_brief_pack.digital_oracle.preset`：推荐的 preset 名（`chief_regime_read`）
- `payload.macro_brief_pack.digital_oracle.wrapper`：`scripts/digital_oracle_query.py` 绝对路径
- `payload.prior_macro_brief`：**必读**——上一份 brief（或 `null`），用于 `prior_brief_review` 自评
- `payload.recent_macro_briefs`：最近 5 份（审阅连续性）

## 调 digital-oracle

```bash
python3 /Users/chenzian/openclaw-trader/scripts/digital_oracle_query.py \
  --preset chief_regime_read \
  --output /tmp/oracle_chief.json
```

preset 应覆盖：Deribit BTC/ETH 期限结构、CFTC COT（BTC/原油/黄金/SPX）、CME FedWatch、US Treasury 曲线、F&G。具体 providers 清单见 `/Users/chenzian/openclaw-trader/skills/digital-oracle/references/providers.md`。

某个 provider 超时或返回空不算失败——在 `data_source_snapshot.digital_oracle_providers_failed` 里列出来，narrative 里承认这块不确定。

## 合成 brief

打开并严格遵循 schema：`specs/modules/agent_gateway/contracts/macro_brief.schema.json`
提示词合约参考：`specs/modules/agent_gateway/contracts/macro_brief.prompt.md`

思考顺序：
1. **现在市场在定价什么？** 把 regime_tags 按顺序填：usd_trend → real_rates → crypto_carry_* → crypto_iv_regime → *_positioning → fed_next_meeting_skew → sentiment_bucket → regime_summary。每个字段用受限词汇（例如 usd_trend ∈ {strong_uptrend, uptrend, range, downtrend, strong_downtrend}）而不是自由句子。
2. **narrative**：300–500 字。用 regime_tags 做骨架，把 digital-oracle 的具体数字嵌进去。不要只是复述新闻，要答"为什么这样判断"。
3. **pm_directives**：每条一句可执行指令。例如"维持 exposure band 上限 ≤ 20%"、"ETH 不加仓"、"若 DXY 突破 108 立刻切 defensive"。PM skill 里有硬约束必须引用这份 directives，所以别写泛泛风险提示——要能被 PM 直接抄进 `portfolio_thesis`。
4. **monitoring_triggers**：会让你（Chief）下一版 brief 改判的信号。不是 PM 的 flip_triggers——写给 Chief 自己在下一天回头看。
5. **prior_brief_review**：四选一。`no_prior` 表示第一份；`falsified` 意味着上一份的 regime_tags 已被实际走势推翻；连续 3 份 `falsified` 会触发系统在 runtime_pack 里加 `chief_regime_confidence: low`，提醒 PM 对 brief 判断打折。
6. **data_source_snapshot**：必须记录 `digital_oracle_preset` / `digital_oracle_providers_used` / `digital_oracle_providers_failed` / `macro_prices_captured_at_utc`，便于后续回放和复盘。

## 提交

```bash
curl -s -X POST http://127.0.0.1:8788/api/agent/submit/macro-brief \
  -H "Content-Type: application/json" \
  --data-binary @/tmp/chief_macro_brief_submit.json
```

`/tmp/chief_macro_brief_submit.json` 里封装：

```json
{
  "input_id": "input_...",
  "payload": {
    "valid_until_utc": "2026-04-21T13:00:00Z",
    "wake_mode": "daily_macro_brief",
    "regime_tags": { "...": "..." },
    "narrative": "...",
    "pm_directives": ["...", "..."],
    "monitoring_triggers": ["...", "..."],
    "prior_brief_review": {"prior_brief_id": "...", "verdict": "partially_validated", "notes": "..."},
    "data_source_snapshot": {"...": "..."}
  }
}
```

## 护栏
- `valid_until_utc` 默认设为 `generated_at + 36h`。FOMC / CPI 日可以缩短。
- **Brief 不可在线修改**。要纠偏就下一次提交一份新 brief。旧 brief 保留可审计。
- 单次 `digital-oracle` 调用失败不得阻塞 brief 产出；承认不确定即可。
- brief 是低频深度判断，不是盘中反应。不要每 15 分钟更新一次。
- 不要在 daily brief 里代替 PM 写 `portfolio_thesis`——你给 directives，PM 保留组合决策权威。
- 绝不发明、转换或摘要 `input_id`——原样复用拉取桥接返回的值。
