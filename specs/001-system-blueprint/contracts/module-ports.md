# 模块端口契约

## 1. 交易网关模块（Trade Gateway）

- **输入**：外部交易所 API、产品元数据、账户事实、执行命令
- **输出**：
  - `MarketSnapshotNormalized`
  - `AccountSnapshot`
  - `MarketContextNormalized`
  - `ExecutionResultReady`

## 2. 新闻事件模块

- **输入**：固定新闻源、公告源、事件源
- **输出**：
  - `NewsBatchReady`
  - `NewsDigestEvent`

## 3. 量化判断模块

- **输入**：`MarketSnapshotNormalized`
- **输出**：
  - `MultiHorizonPredictionReady`
  - `QuantDiagnosticsReady`

## 4. 风控与执行守卫模块

- **输入**：
  - `MultiHorizonPredictionReady`
  - `NewsDigestEvent`
  - `AccountSnapshot`
- **输出**：
  - `RiskGuardDecisionReady`

## 5. 状态机与编排器模块

- **输入**：
  - `ManualTriggerCommand`
  - `NewsBatchReady`
  - `StrategySubmitted`
  - `ExecutionResultReady`
- **输出**：
  - `WorkflowStateTransitioned`
  - `AgentTaskRequested`
  - `ExecutionRequested`
  - `NotificationRequested`

## 6. 多智能体协作网关模块

- **输入**：
  - `AgentTaskRequested`
  - 结构化事实包
- **输出**：
  - `StrategySubmitted`
  - `NewsSubmitted`
  - `ExecutionSubmitted`
  - `AgentEscalationRaised`

## 7. 记忆资产模块

- **输入**：
  - 所有重要事件与状态迁移
- **输出**：
  - `StateSnapshotReady`
  - `MemoryViewReady`
  - `MemoryProjectionReady`

## 8. 通知服务模块

- **输入**：
  - `NotificationRequested`
- **输出**：
  - `NotificationDelivered`
  - `NotificationFailed`

## 9. 回放与前端模块

- **输入**：
  - 标准事件流
  - 查询读模型
- **输出**：
  - 实时 UI
  - 历史回放
  - 调参界面
