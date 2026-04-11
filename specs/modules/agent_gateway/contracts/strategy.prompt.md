# strategy prompt contract

把 `strategy.schema.json` 作为正式提交合同附加到 PM 的正式提交通道中。

要求：

- 只输出符合 schema 的 JSON
- 不输出 markdown 包裹
- 不输出系统字段；正式资产里的 `strategy_id`、`strategy_day_utc`、`generated_at_utc`、`trigger_type` 由系统补齐
- `targets[]` 只表达目标状态与 RT 的执行边界，不表达执行路径
- 每个 `target` 都要显式填写 `rt_discretion_band_pct`
- 所有持仓/暴露相关百分比统一按 `total_equity_usd * max_leverage` 的 exposure budget 口径表达
- `flip_triggers` 必须写成一句或几句明确条件，表达什么情况下应从当前方向翻到反向，而不是只写泛泛风险提示
- `scheduled_rechecks[]` 的 `reason` 要写成留给未来的一句话
