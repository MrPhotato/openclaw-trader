# 研究记录：PM

## 决策 1：PM 只输出目标状态

- **Decision**：PM 的正式输出是 `strategy` JSON，只表达目标组合和重看计划，不表达执行路径。
- **Rationale**：这样不会锁死 RT 的执行逻辑，也符合真实组合经理职责。
- **Alternatives considered**：
  - 在 PM 输出中加入执行指令：会越界到 RT。

## 决策 2：PM 不自管长期记忆

- **Decision**：PM 的长期记忆只由 `memory_assets` 托管。
- **Rationale**：PM 记忆的真相应是“正式定过什么”，而不是聊天 transcript 或草稿。
- **Alternatives considered**：
  - 保留 PM 私有记忆：会制造第二真相源。

## 决策 3：PM 正式提交统一经 AG 校验

- **Decision**：PM 通过 `agent_gateway` 的 `strategy` schema 提交正式策略。
- **Rationale**：统一正式提交流程，避免 PM 例外化。
- **Alternatives considered**：
  - PM 直接写 `memory_assets`：会绕过统一准入层。
