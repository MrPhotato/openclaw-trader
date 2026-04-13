# 正式输出

提交前，打开并严格遵循以下 schema：
- `specs/modules/agent_gateway/contracts/news.schema.json`

Prompt 合约参考：
- `specs/modules/agent_gateway/contracts/news.prompt.md`

规则：
- 正式提交必须是恰好一个 JSON 对象。
- 保留运行时包中的 `input_id`，并在调用 submit bridge 时一并发送。
- 仅输出 JSON。不得输出 markdown 围栏、散文、旁注或尾部说明。
- 仅提交结构化事件列表。不要添加 `submission_id` 或 `generated_at_utc`；系统会自动生成。
- 每条事件摘要应保持简洁。
- 不要输出 `alert` 字段。
- 对 `PM` 和 `RT` 的直接提醒属于对话行为，不是正式提交字段。
