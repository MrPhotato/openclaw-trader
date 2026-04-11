# 研究记录：事件协议与进程内总线骨架

## 决策 1：统一使用单一 `EventEnvelope`

- **Decision**：所有模块输出统一使用单一事件信封，业务差异只放进 `payload`。
- **Rationale**：前端回放、进程内事件总线、中间层日志和通知都需要可共享的顶层字段。
- **Alternatives considered**：
  - 每类模块自定义顶层字段：会导致前端和总线消费者重复适配。
  - 仅靠文本日志：不可回放，也不适合多 Agent 协作。

## 决策 2：进程内事件总线使用稳定的 `event_type` 命名

- **Decision**：统一采用 `<domain>.<entity>.<state>` 的 `event_type` 规则，并将主正确性链落在 `memory_assets`，进程内总线只承担发布与观察。
- **Rationale**：适合模块化系统逐步扩容，也便于前端、通知、回放按前缀聚合事件。
- **Alternatives considered**：
  - 继续依赖文本日志：无法作为长期协作骨架。
  - 仅靠数据库快照：无法表达流程事件和命令回执。

## 决策 3：参数治理只定义最小审计闭环

- **Decision**：本 feature 只定义参数变更请求、参数变更记录、参数生效事件和回滚引用。
- **Rationale**：当前阶段需要的是审计和接口约束，不是完整参数平台。
- **Alternatives considered**：
  - 直接在本 feature 定义完整参数服务：超出当前范围。
  - 完全后置参数治理：会让后续 feature 各自发明 override 语义。

## 决策 4：公共协议不携带模块内部业务规则

- **Decision**：事件协议、交付协议和参数协议都不包含策略、风控或交易算法规则。
- **Rationale**：避免 `002` 变成一个隐式业务 feature。
- **Alternatives considered**：
  - 把业务细节一起塞进公共协议：会导致 `003-007` 边界再次混乱。
