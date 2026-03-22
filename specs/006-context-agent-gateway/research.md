# 研究记录：上下文视图与多智能体网关

## 决策 1：结构化输入先于 prompt

- **Decision**：先定义角色化 `AgentRuntimeInput`，再由任何实现层把它编译成 prompt 或其他输入形式。
- **Rationale**：避免再次回到散装 prompt 时代。
- **Alternatives considered**：
  - 直接定义 prompt 模板：会把实现细节写死。

## 决策 2：OpenClaw 视为外部网关

- **Decision**：OpenClaw 只通过网关模块接入，不直接进入业务域。
- **Rationale**：保持业务系统与协作环境解耦。
- **Alternatives considered**：
  - 让 OpenClaw 深度嵌入 dispatcher：会重复当前问题。

## 决策 3：升级必须结构化

- **Decision**：任何 Agent 无法处理的情况都必须输出 `AgentEscalation`。
- **Rationale**：避免单 Agent 模式下常见的静默失败。
- **Alternatives considered**：
  - 允许纯文本升级：不利于回放和状态跟踪。
