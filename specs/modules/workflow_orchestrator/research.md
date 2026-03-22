# 研究记录：Workflow Orchestrator

## 决策 1：只做客观唤醒，不做 MEA 内容路由

- **Decision**：`workflow_orchestrator` 在 `MEA` 主线中只负责客观唤醒、生命周期管理和正式收口
- **Rationale**：`MEA -> PM/RT/Chief` 的直接沟通属于协作层，不属于控制面
- **Alternatives considered**：保留 `MEA result -> WO -> agent` 路由；结论是会重新把协作层收死

## 决策 2：MEA 计时器固定为 2 小时并由 NEWS_BATCH_READY 重置

- **Decision**：基础巡检 `2h`，批次到达即刻唤醒并重置计时器
- **Rationale**：与 MEA 的真实工作节奏一致
- **Alternatives considered**：只依赖定时器或只依赖新闻触发；结论是两者并行更合理

## 决策 3：高等级事件只先保留挂载规则

- **Decision**：保留 `13` 任务 / `12` 任务挂载规则，但不提前拍死最终提交归属
- **Rationale**：当前规则已定，但正式收口归属尚未最终决定
- **Alternatives considered**：本轮直接把归属绑定给 `workflow_orchestrator`；结论是会超前锁死未定问题

## 决策 4：PM 正式策略进入 WO 只看 recheck 元数据

- **Decision**：`workflow_orchestrator` 订阅 PM 的正式 `strategy` 提交，但只消费 `scheduled_rechecks[]` 和“收到新策略触发一次 RT 决策”的规则
- **Rationale**：WO 需要做调度，但不应解释完整策略
- **Alternatives considered**：让 WO 消费整个策略语义；结论是会重新膨胀为策略中枢
