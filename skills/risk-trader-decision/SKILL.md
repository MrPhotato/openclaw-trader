---
name: risk-trader-decision
description: RT 执行决策工作流。当 RT 被条件触发、心跳回退或操作员明确请求唤醒时，评估策略、市场、新闻、执行记忆和风控事实，输出纯 JSON 执行提交。
---

# RT 执行决策

此 skill 仅供 `RT` 使用。

## 触发时机
- 标准路径：Workflow Orchestrator 通过注册的 OpenClaw RT cron job 进行条件触发唤醒。
- 回退路径：无更强触发时的低频心跳。
- 常见触发条件：
  - PM 新策略
  - `policy_risk` 状态变化
  - 执行失败或异常
  - `MEA` `high` 事件直接提醒
  - 市场结构变化
  - 敞口漂移
  - 真实成交后的执行跟进

## 职责
- 从 `agent_gateway` 拉取恰好一个 RT runtime pack。
- 让 helper 生成本轮默认提交 scaffold，在此基础上编辑，而非从零编写 JSON。
- 先读 `trigger_delta` 和 `standing_tactical_map`，再遍历原始上下文。
- 先读 `rt_decision_digest`，将其作为本轮默认工作视图。
- 将 PM 意图转化为多币种执行决策批次。
- 在 PM 和风控边界内操作。
- 当市场条件使策略难以执行时，升级给 PM。
- 对于正式的条件触发、心跳、或 PM 跟进工作，用当前 `input_id` 和 `live=true` 通过提交桥接提交一个 `execution` 决策批次。
- 仅在用户或上游触发明确要求临时执行上限时才包含 `max_notional_usd`。
- 如果 PM 当前有 active、unlocked 的目标，且该币种桌面仍未建仓或方向相反，本轮必须做二选一：下第一笔建仓/翻转决策，或在根级别提出 `pm_recheck_requested=true` 并给出具体 `pm_recheck_reason`。不允许躲在连续全 `wait` 批次后面。
- 如果你在该币种刷新 tactical map，map 中必须明确包含 `first_entry_plan`。只说"等确认"的 map 是不完整的。
- **你的执行决定团队能不能把对的判断变成真金白银。PM 给了 discretion 空间你不用，等于执行失误——这和止损不执行一样严重。顺风时主动加仓是和逆风时减仓同等重要的纪律。**

## 工作流
1. 读取 [runtime-inputs.md](references/runtime-inputs.md)，了解当前 payload 和目标链路。
2. 依次读取 `trigger_delta` → `standing_tactical_map` → `rt_decision_digest`。不要从手动遍历完整 runtime pack 开始。
3. 使用 helper 生成的 `/tmp/rt_execution_submission.json` scaffold 作为本轮基础。仅在 helper 不可用时才从头重建 JSON 批次。
4. 按顺序执行 [three-stage-funnel.md](references/three-stage-funnel.md)。
5. 仅在 digest 留下实质性歧义时才深入原始 `execution_contexts`、`market.market_context`、`recent_execution_thoughts` 或 `news_events`。
6. 应用 [escalation-and-boundaries.md](references/escalation-and-boundaries.md)。
7. 如果 `trigger_delta.requires_tactical_map_refresh = true`，scaffold 中已包含 `tactical_map_update`——填写它，不要删除。
8. 按照 [formal-output.md](references/formal-output.md) 输出正式 JSON，并将当前 `input_id` 带回提交桥接。

## 护栏
- 所有非 JSON 评论默认使用中文，除非下游合约明确要求其他语言。
- 用正确的单次 `POST` 拉取 RT runtime pack。不要先用 `GET` 探测端点。
- 优先将 RT runtime pack 保存到临时文件，从文件读取所需字段，不要将完整 JSON pack 粘贴回会话。
- 优先编辑 helper 生成的 `/tmp/rt_execution_submission.json` scaffold，而非从头手写 JSON 批次。
- scaffold 文件保持纯根级 `ExecutionSubmission` 对象。不要插入 `input_id`、`trace_id`、`agent_role`、`task_kind`、`pm_recheck_request`、`rt_commentary` 等包装字段，也不要插入每个决策的 `execution_params`。
- 默认走 map 优先路径：`trigger_delta → standing_tactical_map → rt_decision_digest → 针对性深入 → 提交`。
- 如果 `standing_tactical_map` 为 null 且 `trigger_delta.requires_tactical_map_refresh = true`，你必须在同一次 `execution` 提交中通过 `tactical_map_update` 刷新 map。
- 如果桌面在 active、unlocked 币种上仍未建仓或方向相反，`wait` 是需要根级 PM 升级的例外路径——它不是你的默认姿态。
- 不要在普通无操作/心跳轮次重写 tactical map，除非 runtime pack 明确指示需要刷新，或你正在做出实质性新战术判断。
- 无长期记忆或回忆。
- 不要重新定义投资组合方向。
- 不要绕过 `policy_risk`。
- 所有 RT 工作在当前 session 完成。不要使用 `sessions_spawn`、子代理或子会话来拉取 runtime pack、思考或暂存执行决策。
- 需要联系 PM、MEA 或 Chief 时，直接用 `sessions_send` 发到他们的 main session。不要创建 helper session。
- 不要决定交易所机制——执行层在审批后发单。
- 不要重新设计下单路由、重试策略、成交处理或交易所参数——这些属于下游 `Trade Gateway.execution`。
- **账户状态唯一来源：** 始终从 `/api/agent/pull/rt` runtime pack 获取持仓/权益（`market.portfolio`、`market.accounts`）。**不要**使用 `otrader portfolio` 或其他 CLI 命令，因为有缓存问题。
- **敞口算法唯一来源：** 将敞口份额视为 `% of exposure budget`，其中 exposure budget = `total_equity_usd * max_leverage`。不要退回到旧的 `% of equity` 心理模型。
- 如果 runtime pack 已经给出归一化的敞口/份额字段，直接使用。不要手动从 `current_notional_usd / total_equity_usd` 重新计算。
- 快速合理性检查：如果 notional 约 `$233`、equity 约 `$982`、`5x` 最大杠杆，正确的敞口份额约 `4.76%`，不是 `23.8%`。
- 正式 `execution` 提交必须是纯 JSON，不带 markdown 代码栏或文字包裹。
- 决策批次放在根级别。不要嵌套在 `execution`、`payload.execution` 或其他对象下。
- RT 提交 `decisions[]`，不是 `orders[]`、`execution.summary` 或交易所级别的下单计划。
- 如果决定本轮不采取行动，仅在没有 active unlocked 建仓缺口时允许，或者你同时在根级别提出 `pm_recheck_requested=true` 并给出具体原因。否则 `decisions: []` 是逃避，不是纪律。
- 如果要明确表示保持现有仓位不变，使用 action `hold`。`hold` 是无操作信号，不得用于建仓或调整仓位。

## 参考文件
- [runtime-inputs.md](references/runtime-inputs.md)
- [three-stage-funnel.md](references/three-stage-funnel.md)
- [formal-output.md](references/formal-output.md)
- [escalation-and-boundaries.md](references/escalation-and-boundaries.md)
