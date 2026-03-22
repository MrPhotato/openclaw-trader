# news prompt contract

把 `news.schema.json` 作为 `MEA` 正式提交合同附加到提交通道中。

要求：

- 只输出符合 schema 的 JSON
- `submission_id` 与 `generated_at_utc` 由系统补齐，不由 `MEA` 编写
- 每个 `events[]` 的 `summary` 控制在 1-2 句
- 不包含 `alert` 字段
