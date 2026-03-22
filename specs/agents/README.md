# Agent 主规格索引

本目录是新的 Agent 级主真相层。  
它记录 4 个 Agent 的真实岗位职责、固定班次、直接沟通边界、正式提交通道与禁止事项。

## 4 个 Agent

| Agent | 目录 | 当前深度 | 记录重点 |
| --- | --- | --- | --- |
| PM | `specs/agents/pm` | 完整套件 | 目标组合、`UTC 01:00` / `UTC 13:00` 固定策略判断、事件驱动额外运行、`strategy` 提交 |
| Risk Trader | `specs/agents/risk_trader` | `spec` | 高频执行判断、JSON `ExecutionDecision`、策略级升级 |
| Macro & Event Analyst | `specs/agents/macro_event_analyst` | 完整套件 | `2h` 巡检、`NEWS_BATCH_READY` 唤醒、结构化事件、直接提醒 PM |
| Crypto Chief | `specs/agents/crypto_chief` | `spec` | owner 沟通、复盘、Learning、升级协调 |

## 使用规则

- Agent `spec.md` 统一记录：真实岗位职责、固定班次与触发、可直接沟通对象、正式提交通道、禁止事项、当前已定、待后续讨论。
- 直接沟通与正式提交必须分开描述。
- 角色特定的 JSON 约束只属于正式提交通道，不是 Agent 的通用说话方式。
