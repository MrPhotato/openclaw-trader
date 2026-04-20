# macro_brief prompt contract

把 `macro_brief.schema.json` 作为正式提交合同附加到 Chief daily macro brief 的正式提交通道中。

要求：

- 只输出符合 schema 的 JSON
- 不输出 markdown 包裹
- 不输出系统字段；正式资产里的 `brief_id`、`generated_at_utc` 由系统补齐
- `valid_until_utc` 默认设为 `generated_at + 36h`（日频 + 12h 容差）；FOMC/CPI 当日可调短
- `narrative` 必须是 300–500 字自然语言 regime 叙事，说明：
  1. 市场当前在定价什么（usd trend / real rates / crypto carry 的综合含义）
  2. 为什么这样判断（数据源要点，不是新闻片段）
  3. 下一步看什么（哪些信号会让 regime 重新评估）
- `pm_directives[]` 是给 PM 的方向性指示；每条一句话、可执行。例如：
  - "保持 BTC exposure band 上限 ≤ 20%"
  - "ETH 不加仓，维持 watch"
  - "若 BTC 跌破 $73K 立刻切 defensive"
- `monitoring_triggers[]` 是会让你（Chief）更新这份 brief 的信号，不是 PM 的 flip_triggers。例如：
  - "Deribit BTC 3M basis < 5%"
  - "DXY 突破 107"
- `prior_brief_review.verdict` 四选一：
  - `no_prior`：第一份 brief
  - `validated`：上一份的 regime_tags 被实际走势验证
  - `partially_validated`：方向对，细节偏
  - `falsified`：regime call 被证伪；连续 3 份证伪会触发 runtime_pack 中的 `chief_regime_confidence: low` 标签
- `data_source_snapshot` 至少记录：
  - `digital_oracle_preset`（例如 `chief_regime_read`）
  - `digital_oracle_providers_used`（成功响应的 provider 列表）
  - `digital_oracle_providers_failed`（超时/空结果的 provider 列表）
  - `macro_prices_captured_at_utc`（runtime_pack 提供的快照时间戳）
