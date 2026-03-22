# OpenClaw / 多智能体协作契约

## 1. 目标

把当前散落在 dispatcher 内的 OpenClaw 调用逻辑，收口为独立协作契约。

## 2. 请求结构

每次给 Agent 的请求都必须包含：

- `task_id`
- `agent_role`
- `task_kind`
- `input_id`
- `context_payload`
- `reply_contract`
- `timeout_seconds`
- `delivery_policy`

## 3. 回执结构

每次 Agent 返回都必须包含：

- `task_id`
- `agent_role`
- `status`：`completed` / `failed` / `needs_escalation`
- `decision_payload`
- `reason`
- `raw_transcript_ref`
- `returned_at`

## 4. 升级结构

升级必须显式建模，而不是隐含在对话里：

- `escalation_id`
- `from_agent_role`
- `to_agent_role`
- `reason_code`
- `summary`
- `required_action`

## 5. 与当前系统的映射

当前：

- `OpenClawAgentRunner.run()` 发起 agent 调用
- `send_text()` 负责发确定性消息
- session target / to / session-id 规则散落在 runner 内部

未来：

- 这些都收口到多智能体协作网关
- dispatcher / 状态机只负责发 AgentTask，不再直接拼 OpenClaw CLI 细节
