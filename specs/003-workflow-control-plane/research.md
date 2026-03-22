# 研究记录：工作流控制平面

## 决策 1：统一使用单控制入口

- **Decision**：所有主动触发都统一进入 `/api/control/commands`。
- **Rationale**：防止后续模块绕过控制平面直接触发业务动作。
- **Alternatives considered**：
  - 每个模块保留独立主动入口：会继续复制调度逻辑。

## 决策 2：状态机使用显式状态记录

- **Decision**：每次工作流实例都保存 `WorkflowStateRecord`，并通过状态迁移事件更新。
- **Rationale**：前端、回放和通知都需要同一状态源。
- **Alternatives considered**：
  - 只靠 transient 事件推断状态：不利于恢复和审计。

## 决策 3：命令必须幂等

- **Decision**：所有手动或系统命令都必须有 `command_id`，重复命令按幂等键处理。
- **Rationale**：避免网络重试、UI 重点和 Agent 回执导致重复动作。
- **Alternatives considered**：
  - 仅靠 trace 去重：不够精确。
