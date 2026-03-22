# 研究记录：策略与执行主脊梁

## 决策 1：策略意图与订单显式分离

- **Decision**：`StrategyIntent` 只描述目标组合和理由，不直接描述交易所订单。
- **Rationale**：这是当前系统安全性的重要来源。
- **Alternatives considered**：
  - 让策略直接输出订单：会破坏守卫与执行判断边界。

## 决策 2：Risk Trader 只处理 ExecutionContext

- **Decision**：`Risk Trader` 只消费 `ExecutionContext`，输出结构化 `ExecutionDecision`，不直接下单。
- **Rationale**：保持策略与执行判断分层，同时避免恢复旧 reviewer 语义。
- **Alternatives considered**：
  - 恢复 `TradeCandidate` / `TradeReviewDecision`：会把旧候选链带回主语义。
  - 让策略直接生成执行动作：边界过宽。

## 决策 3：统一动作集合

- **Decision**：执行动作用 `open/add/reduce/close/flip/wait` 六类。
- **Rationale**：可覆盖当前永续执行主路径，又允许显式表达“暂不执行”。
- **Alternatives considered**：
  - 沿用当前不同交易所适配层的命名差异：会污染上层契约。
