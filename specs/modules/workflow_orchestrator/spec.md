# 模块规格说明：Workflow Orchestrator

**状态**：主真相层草案  
**对应实现**：`src/openclaw_trader/modules/workflow_orchestrator/`  
**来源承接**：`001`、`003`

## 1. 背景与目标

`workflow_orchestrator` 是统一复杂调度、工作流生命周期管理和异常收口模块。它收口客观触发、recheck 编排、状态迁移和正式收口，但不再承担 Agent 内容路由中心的角色。固定交易/分析班次由 OpenClaw `cron` 负责，而每日 session reset 由 `workflow_orchestrator` 在 `UTC 00:30` 统一执行。

## 2. 职责

- 提供统一主动控制入口
- 维护显式状态机、命令幂等和生命周期记录
- 维护复杂调度与事件触发，不承担固定班次 owner
- 在每天 `UTC 00:30` 统一对 `PM / RT / MEA / Chief` 执行 `/new`
- 消费 PM 正式策略中的 `scheduled_rechecks[]`，注册未来重看任务
- 在收到新的 PM 正式策略后触发一次 RT 决策
- 在执行异常、风控变化或其他客观事件到来时协调额外唤醒
- 在收到 `NEWS_BATCH_READY` 时立即要求 `MEA` 尽快拉取最新 runtime pack
- 触发并收口由 `agent_gateway` 驱动的内部复盘会
- 提供 trigger context 和 runtime pack 发放/消费记录能力

## 3. 拥有资产

- `ManualTriggerCommand`
- `WorkflowCommandReceipt`
- `WorkflowStateRecord`
- MEA 计时器与策略 recheck 调度元数据

## 4. 输入

- 外部主动命令
- `NEWS_BATCH_READY`
- OpenClaw `cron` 产生的固定班次唤醒
- 其他模块的正式提交回执
- 通过 `agent_gateway` 校验后的 `strategy` 正式提交
- RT 执行异常类客观事件

## 5. 输出

- 工作流状态迁移记录
- recheck、异常补跑与客观唤醒命令
- trigger context 与 runtime pack 生命周期记录
- 面向 `memory_assets` 的正式收口引用
- 临时复盘会 transcript 的调试引用

## 6. 直接协作边界

- 向 `news_events` 订阅批次就绪信号
- 向 `agent_gateway` 暴露 trigger context、recheck 状态和生命周期读桥
- 向 `memory_assets` 提交工作流状态和正式收口记录

## 7. 不负责什么

- 不订阅 `MEA` 的结果内容
- 不做 `MEA -> PM/RT/Chief` 的内容中转
- 不解释完整策略、风险和执行语义
- 不再为 `PM / RT / MEA / Chief` 的固定班次主动组装运行时 payload

## 8. 当前已定

- `MEA` 基础巡检周期为 `2` 小时
- PM 固定策略判断班次为 `UTC 01:00` 与 `UTC 13:00`
- RT 固定执行巡检周期为 `10` 分钟
- Chief 固定复盘班次由 OpenClaw `cron` 在每天 `UTC 23:00` 直接唤醒
- OpenClaw `cron` 是 PM / RT / MEA / Chief 的固定班次 owner
- `workflow_orchestrator` 在每天 `UTC 00:30` 统一执行 4 个 agent 的 session reset
- `workflow_orchestrator` 在固定班次之外继续负责复杂调度、recheck 和事件驱动额外唤醒
- `NEWS_BATCH_READY` 仍会产生即时唤醒语义，但由被唤醒的 agent 自己拉取最新 runtime pack
- `workflow_orchestrator` 不订阅也不转发 `MEA` 结果内容
- `workflow_orchestrator` 只消费 PM 正式策略里的 recheck 元数据
- 每次收到新的 PM 正式策略都触发一次 RT 决策
- 风控变化、执行异常和 `MEA` 提醒可立即触发 RT 决策
- 若 execution 在网络/技术错误下连续 `5` 分钟仍无法提交成功，应通过 MQ 发异常事件并由 `workflow_orchestrator` 立即唤醒 RT
- `workflow_orchestrator` 向 `agent_gateway` 提供：
  - `get_trigger_context`
  - `record_runtime_pack_issued`
  - `record_runtime_pack_consumed`
  - `record_recheck_state`
- `high` 级事件不再由 `workflow_orchestrator` 托管跟踪；由 `MEA` 直接口头提醒相关 Agent
- `run_chief_retro` 只负责触发和收口内部复盘会，不直接主持会议内容
- 复盘会后顺序固定为：Chief 发出 learning 指令 -> owner summary
- session `/new` 不在 retro 流程内执行；改为由 `workflow_orchestrator` 每天 `UTC 00:30` 统一执行
- `workflow_orchestrator` 不把内部复盘会 transcript 写成正式资产
- 任一 retro speaker turn 若出现 timeout、gateway/provider 错误或其他 transport failure，workflow 必须明确进入 `degraded`，不得长期停留在 `running`

## 9. 待后续讨论

- 后台长驻扫描、fallback 和 daily report 的完整状态机
