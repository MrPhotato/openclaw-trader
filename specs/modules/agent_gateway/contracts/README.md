# Agent Gateway Contracts

本目录维护 `agent_gateway` 负责校验的三类正式提交模板：

- `news.schema.json`
- `strategy.schema.json`
- `execution.schema.json`

每类模板都配套：

- 对应的 `*.prompt.md`
- 至少一个 `*.example.json`

规则：

- schema 是独立 JSON 文件
- schema 同时可作为 prompt 拼接输入的一部分
- 业务模块只消费通过 AG 校验后的正式提交
