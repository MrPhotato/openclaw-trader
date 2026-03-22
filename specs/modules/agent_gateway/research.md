# 研究记录：Agent Gateway

## 决策 1：正式提交模板统一收口到 AG

- **Decision**：`news`、`strategy`、`execution` 三类正式提交模板统一由 `agent_gateway` 拥有与校验。
- **Rationale**：这样可以保证各 Agent 的准入规则一致，不把 schema 校验散落到业务模块。
- **Alternatives considered**：
  - 由各业务模块各自校验：会造成重复校验与合同漂移。

## 决策 2：schema 与 prompt 同源但不同文件

- **Decision**：schema 以独立 JSON 文件存在，并与 `prompt.md`、example 同目录维护。
- **Rationale**：既保持机器可校验合同，也方便把 schema 作为 prompt 拼接输入的一部分。
- **Alternatives considered**：
  - 把 schema 和 prompt 写在同一文件：机器校验和提示词维护会互相牵制。

## 决策 3：下游不重复做 schema 准入校验

- **Decision**：业务模块只消费通过 AG 校验后的正式提交，不重复做准入校验。
- **Rationale**：这样可以统一入口并减少跨模块打回。
- **Alternatives considered**：
  - 每个消费者再次做 schema 校验：会带来重复处理和边界混乱。
