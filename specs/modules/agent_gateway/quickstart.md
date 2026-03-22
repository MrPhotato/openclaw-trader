# Quickstart：Agent Gateway

1. Agent 先完成自由协作或独立思考。
2. Agent 通过正式提交通道提交 `news`、`strategy` 或 `execution` JSON。
3. `agent_gateway` 依据对应 schema 做准入校验。
4. 校验通过后，AG 生成 `ValidatedSubmissionEnvelope` 并发往消息总线。
5. 对应消费者订阅并处理各自语义。
6. 若校验失败，AG 把 `schema_ref`、`prompt_ref` 和错误列表返回给原 Agent，要求其重新生成纯 JSON。

## 场景 2：复盘会收尾

1. `Crypto Chief` 在会议结束时要求四个 Agent 各自在自己的 session 中调用 `/self-improving-agent`。
2. `Crypto Chief` 不等待 learning 结果，直接给 owner summary。
3. `workflow_orchestrator` 在每日 `UTC 00:30` 统一对 `PM`、`Risk Trader`、`Macro & Event Analyst`、`Crypto Chief` 的既有 session 各发送一次 `/new`。

## 关键约束

- 直接沟通不受 JSON 合同约束
- 正式提交必须命中共享 schema
- 业务模块不重复做 schema 准入校验
