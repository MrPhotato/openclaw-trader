# execution prompt contract

把 `execution.schema.json` 作为 `Risk Trader` 正式提交合同附加到提交通道中。

要求：

- 只输出符合 schema 的 JSON
- `decisions[]` 可以包含多个币的短执行批次
- `decisions[]` 只使用约定动作集合，并且必须遵守 PM 给出的 `target_exposure_band_pct` 与 `rt_discretion_band_pct`
- `size_pct_of_exposure_budget` 表示 `% of exposure budget`，分母为 `total_equity_usd * max_leverage`
- 若当前不执行，只有在不存在 active unlocked entry gap 时才可返回 `wait` 或空批次
- 若存在 active unlocked entry gap 但 RT 拒绝立即开首笔，必须在根级带上 `pm_recheck_requested=true` 与非空 `pm_recheck_reason`
- 若这轮同时刷新 `tactical_map_update`，则每个 active unlocked entry gap 对应的币种都必须带非空 `first_entry_plan`
