# 研究记录：市场智能与风险守卫

## 决策 1：沿用当前 `12h/4h/1h` 职责分层

- **Decision**：`12h` 作为方向锚，`4h` 作为开仓/加仓决策层，`1h` 仅用于已有仓位减仓/延后。
- **Rationale**：这是当前 live 主路径已经验证过的职责分层。
- **Alternatives considered**：
  - 让 `1h` 重新控制开仓：与现有经验相冲突。

## 决策 2：新闻先结构化，再进入上下文层

- **Decision**：后续模块只消费 `NewsEventMaterialized` 和摘要，不直接读原始 RSS/HTML。
- **Rationale**：避免策略、Agent 和前端重复解析新闻。
- **Alternatives considered**：
  - 各模块自行消费新闻源：会再次造成上下文分裂。

## 决策 3：`policy_risk` 是最终硬风控边界

- **Decision**：风险守卫输出必须独立成可消费实体，后续模块不得绕过；该实体是 `RiskGuardDecisionReady`，而不是旧软建议层。
- **Rationale**：当前系统真正需要的是可执行的硬边界，而不是保留旧软建议残影。
- **Alternatives considered**：
  - 让后续模块重复计算允许动作：会破坏单一真相源。
