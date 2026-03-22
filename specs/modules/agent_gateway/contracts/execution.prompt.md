# execution prompt contract

把 `execution.schema.json` 作为 `Risk Trader` 正式提交合同附加到提交通道中。

要求：

- 只输出符合 schema 的 JSON
- `decisions[]` 可以包含多个币的短执行批次
- `decisions[]` 只使用约定动作集合，并且必须遵守 PM 给出的 `rt_discretion_band_pct` 与 `no_new_risk`
- `size_pct_of_equity` 虽沿用旧字段名，但语义统一为 `% of exposure budget`，分母为 `total_equity_usd * max_leverage`
- 若当前不执行，可返回 `wait`
