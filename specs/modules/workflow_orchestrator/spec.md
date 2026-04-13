# 模块规格说明：Workflow Orchestrator

**状态**：主真相层草案  
**对应实现**：`src/openclaw_trader/modules/workflow_orchestrator/`  
**来源承接**：`001`、`003`

## 1. 背景与目标

`workflow_orchestrator` 是统一复杂调度、工作流生命周期管理和异常收口模块。它收口客观触发、recheck 编排、状态迁移和正式收口，但不再承担 Agent 内容路由中心的角色。固定交易/分析班次由 OpenClaw `cron` 负责，RT 条件触发和风险峰值刹车由 `workflow_orchestrator` 轻量扫描后调用标准 OpenClaw cron job 或系统风控单完成，而每日 session reset 由 `workflow_orchestrator` 在 `UTC 00:30` 统一执行。

## 2. 职责

- 提供统一主动控制入口
- 维护显式状态机、命令幂等和生命周期记录
- 维护复杂调度与事件触发，不承担固定班次 owner
- 维护 RT 条件触发扫描，但只判断客观事实是否需要唤醒 RT，不解释交易语义、不生成 RT payload
- 维护风险峰值刹车扫描，但只负责识别客观风控上升沿、执行系统风控单并触发 RT / PM，不解释交易观点
- 在每天 `UTC 00:30` 统一对 `PM / RT / MEA / Chief` 执行 `/new`
- 消费 PM 正式策略中的 `scheduled_rechecks[]`，注册未来重看任务
- 在收到新的 PM 正式策略后通过 `openclaw cron run <rt_job_id>` 触发一次标准 RT job
- 在执行成交复查、风控变化、敞口漂移、市场结构变化、MEA 高危事件或低频 heartbeat 到来时协调额外 RT 唤醒
- 在收到 `NEWS_BATCH_READY` 时立即要求 `MEA` 尽快拉取最新 runtime pack
- 触发并收口由 `agent_gateway` 驱动的内部复盘会
- 提供 trigger context 和 runtime pack 发放/消费记录能力

## 3. 拥有资产

- `ManualTriggerCommand`
- `WorkflowCommandReceipt`
- `WorkflowStateRecord`
- MEA 计时器与策略 recheck 调度元数据
- `RTTriggerState`
- `RTTriggerEvent`
- `RiskBrakeState`
- `RiskBrakeEvent`

## 4. 输入

- 外部主动命令
- `NEWS_BATCH_READY`
- OpenClaw `cron` 产生的固定班次唤醒
- 其他模块的正式提交回执
- 通过 `agent_gateway` 校验后的 `strategy` 正式提交
- RT 执行异常/成交回执类客观事件
- PM 最新策略资产、MEA 高危事件资产、市场结构与持仓事实
- `policy_risk` 评估出的 `position_risk_state` 与 `portfolio_risk_state`

## 5. 输出

- 工作流状态迁移记录
- recheck、异常补跑与客观唤醒命令
- trigger context 与 runtime pack 生命周期记录
- `rt_trigger_event`，供 RT 下一次 `pull/rt` 时理解自己为什么被唤醒
- `risk_brake_event`，供 PM / RT 下一次 `pull` 时理解系统刚刚替 desk 做了什么风险动作
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
- 不调用旧 `run_rt` / `dispatch_once` / WO-first 推送路径来触发 RT
- 不新建独立订单子系统；系统风控单必须复用现有 execution 链

## 8. 当前已定

- `MEA` 基础巡检周期为 `2` 小时
- PM 固定策略判断班次由 OpenClaw `cron` 配置决定
- RT 固定执行巡检可由用户保留或禁用；条件触发只通过 `openclaw cron run <rt_job_id>` 复用现有标准 RT job
- Chief retro 主触发由 `workflow_orchestrator` 在 `retro_case + retro_briefs` 就绪后直接调用现有 Chief cron job
- OpenClaw `cron` 是 PM / RT / MEA / Chief 的固定班次 owner
- `workflow_orchestrator` 在每天 `UTC 00:30` 统一执行 4 个 agent 的 session reset
- `workflow_orchestrator` 在固定班次之外继续负责复杂调度、recheck 和事件驱动额外唤醒
- `NEWS_BATCH_READY` 仍会产生即时唤醒语义，但由被唤醒的 agent 自己拉取最新 runtime pack
- `workflow_orchestrator` 不订阅也不转发 `MEA` 结果内容
- `workflow_orchestrator` 只消费 PM 正式策略里的 recheck 元数据
- 每次收到新的 PM 正式策略都触发一次 RT 条件唤醒，且该触发可绕过普通冷却
- 风险峰值刹车默认关闭，需由配置显式打开
- 单仓峰值刹车与组合高点刹车统一由 `workflow_orchestrator` 轻量扫描并只在上升沿触发动作
- `observe` 只记录，不自动下系统单
- `reduce / exit` 一旦触发，系统先自动执行风控单，再同时触发 RT 与 PM
- RT 的第一次风控唤醒可绕过普通 cooldown，用于复查系统刚做的风险动作
- PM 新策略落库后，继续沿用现有 `pm_strategy_update -> RT` 条件触发，形成 RT 第二次接棒
- 单仓 `reduce` 只减该币一半；单仓 `exit` 只平该币
- 组合 `reduce` 只减当前浮亏仓位；组合 `exit` 平掉所有非零仓位
- 系统风控单统一沿用现有 execution 链，`actor_role = system`
- 系统风控单前缀固定为 `risk_reduce_*` 或 `risk_exit_*`
- `reduce` 后相关作用域进入 `reduce_only`；`exit` 后进入 `flat_only`
- `reduce_only / flat_only` 统一由新的 PM strategy revision 释放
- `critical` 新闻/事件可绕过普通冷却；`high` 新闻/事件走普通冷却
- 有仓位或 PM active/reduce target 的币，若出现 `range -> up_breakout/down_breakout`、1h high/low 穿越或 volatility expanding，可触发 RT
- flat/watch 且无持仓的币不因单纯 breakout 触发 RT，避免追突破噪音
- 单币或组合敞口偏离 PM 目标带超过 `2% exposure budget` 时可触发 RT
- 成功成交且有 fills 后 `3-5` 分钟内触发一次 RT 复查，同一 execution result 只触发一次
- 有持仓时 `60` 分钟 heartbeat；空仓时 `120` 分钟 heartbeat
- RT 条件触发使用全局冷却 `5` 分钟、同币同类冷却 `15` 分钟、每小时普通触发上限 `4` 次
- 若 `openclaw cron list --json` 显示 RT job 正在运行，只记录 `rt_trigger_event.skipped_reason = cron_running`，不重复入队
- `openclaw cron run` 子进程超时为 `15` 秒；失败时记录 stderr 摘要，不阻塞 WO 线程
- 若 execution 在网络/技术错误下连续 `5` 分钟仍无法提交成功，应通过 MQ 发异常事件并由 `workflow_orchestrator` 立即唤醒 RT
- `workflow_orchestrator` 向 `agent_gateway` 提供：
  - `get_trigger_context`
  - `record_runtime_pack_issued`
  - `record_runtime_pack_consumed`
  - `record_recheck_state`
- `high` 级事件不再由 `workflow_orchestrator` 托管跟踪；由 `MEA` 直接口头提醒相关 Agent
- `run_retro_prep` 只负责手动触发 retro prep；Chief synthesis 由 WO 在 briefs ready 后直接 `cron run`
- 复盘会后顺序固定为：Chief 发出 learning 指令 -> owner summary
- session `/new` 不在 retro 流程内执行；改为由 `workflow_orchestrator` 每天 `UTC 00:30` 统一执行
- `workflow_orchestrator` 不把内部复盘会 transcript 写成正式资产
- 任一 retro speaker turn 若出现 timeout、gateway/provider 错误或其他 transport failure，workflow 必须明确进入 `degraded`，不得长期停留在 `running`

## 9. 待后续讨论

- 后台长驻扫描、fallback 和 daily report 的完整状态机
