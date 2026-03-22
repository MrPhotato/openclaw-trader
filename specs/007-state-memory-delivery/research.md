# 研究记录：状态、记忆与交付层

## 决策 1：状态、记忆、回放三者分层

- **Decision**：状态快照、记忆视图和回放读模型分别定义，不混在同一载体里。
- **Rationale**：避免再次回到“SQLite、brief、日志各说各话”。
- **Alternatives considered**：
  - 继续把所有事实写进同一文件层：不可维护。

## 决策 2：通知只接受结构化命令

- **Decision**：通知服务只消费 `NotificationCommand`，返回 `NotificationResult`。
- **Rationale**：把内容生成和投递动作分开。
- **Alternatives considered**：
  - 继续让通知层直接拼消息：边界不清晰。

## 决策 3：前端只消费读模型和事件

- **Decision**：前端和回放通过事件流与查询读模型工作，不直接读取零散 logs。
- **Rationale**：便于长期维护和模块协作可视化。
- **Alternatives considered**：
  - 直接读取日志文件：短期能跑，长期不稳。
