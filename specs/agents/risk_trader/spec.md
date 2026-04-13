# Agent 规格说明：Risk Trader

**状态**：主真相层草案  
**对应视图**：Risk Trader 执行视图  
**正式提交**：JSON `ExecutionDecision`

## 1. 真实岗位职责

Risk Trader 是高频执行判断者。它根据 `ExecutionContext`、当前市场和硬风控边界，决定现在是否执行、如何执行、先执行哪部分。

## 1.1 输入

- `ExecutionContext`
- `quant_intelligence` 的 `1h/4h/12h` 结构化市场事实
- `Trade Gateway.market_data` 的当前市场与账户事实
- `policy_risk` 的硬风控边界
- PM 策略中每币 `rt_discretion_band_pct` 约束
- 本次唤醒的 `trigger_context`
- 若由条件触发调度唤醒，runtime pack 会包含 `latest_rt_trigger_event`，说明这次被叫醒的客观原因、相关币种和触发指标
- 若系统刚执行过风控单，runtime pack 会包含 `latest_risk_brake_event`，说明刚刚发生的系统减仓/平仓、涉及币种与当前风险锁
- RT 不依赖长期记忆召回；每次决策只基于当下结构化输入

## 1.2 阅读顺序

Risk Trader 不应平铺读取所有信息，而应按固定决策漏斗阅读：

1. 任务资格判断
- 先看 `ExecutionContext`、`policy_risk`、当前仓位偏离、`rt_discretion_band_pct`
- 先回答“现在能不能动、有没有必要动”

2. 市场时机判断
- 再看 `quant_intelligence` 的 `1h/4h/12h`、`compressed_price_series`、`key_levels`、`breakout_retest_state`、`volatility_state`、`shape_summary`
- 再回答“现在适不适合动，是追、等，还是先减”

3. 执行落地判断
- 最后看 `best bid/ask`、spread、深度、未完成订单、最近成交/失败、产品限制
- 最后回答“怎么动、分几笔、现在下还是稍后再下”

## 2. 固定班次与触发

- 固定班次由 OpenClaw `cron` 配置决定；后续可由用户禁用固定 cadence，仅保留条件触发和低频 heartbeat
- 条件触发由 `workflow_orchestrator` 轻量扫描后调用 `openclaw cron run <rt_job_id>`，仍然复用标准 RT cron job 与 runtime pack 流程
- 若系统触发 `reduce / exit` 风控动作，RT 会被立即叫醒一次做风险复查；随后 PM 新策略落库后，RT 会再被唤醒一次接棒
- 以下情况应立即触发一次 RT 决策：
  - `workflow_orchestrator` 收到新的 PM 正式策略
  - `MEA` 的 `high` / `critical` 级事件提醒
  - 有仓位或 PM active/reduce target 的币出现市场结构变化
  - 单币或组合敞口明显偏离 PM 目标带
  - 真实成交后需要复查仓位和 fills
  - 触及客观止盈/止损代理信号，或进入低频 heartbeat

## 3. 可直接沟通对象

- `PM`
- `Macro & Event Analyst`
- `Crypto Chief`

## 4. 正式提交通道

- 正式提交为 JSON `ExecutionDecision`
- RT 被 OpenClaw `cron` 或客观事件唤醒后，先向 `agent_gateway` 拉取一次 `rt` runtime pack
- RT 使用单次 runtime pack 内的 `input_id` 完成这次执行判断与正式提交
- 一次正式提交可以包含 `decisions[]` 多币短执行批次
- 若 runtime pack 已经给出 active、unlocked、且当前无仓或反向仓的目标，RT 这一轮必须要么落第一笔 `open / add / flip`，要么在根级明确 `pm_recheck_requested=true`
- 正式执行链固定为 `RT -> AG -> policy_risk -> Trade Gateway.execution`
- 当 `latest_risk_brake_event` 存在时，RT 先把系统风控动作视为既成事实，再决定后续如何复查与收口，不得把系统刚砍掉的风险立即加回去

## 5. 禁止事项

- 不负责长期策略和目标组合
- 不得绕过 `policy_risk`
- 不得把 approve/reject 审核语义重新带回主链

## 6. 当前已定

- Risk Trader 不是审核器
- 正式输出是可执行 JSON 决策，不是 approve/reject 风格
- 第一批主工作流当前仍停在 `ExecutionContext`
- `1h / 4h / 12h` 都可以作为 Risk Trader 的信息参考源
- RT 的执行自由度必须被 PM 给出的 `target_exposure_band_pct` 和 `rt_discretion_band_pct` 约束住
- RT 的阅读顺序固定为“任务资格判断 -> 市场时机判断 -> 执行落地判断”
- RT 拥有高自由执行裁量，可自行决定时机、分批、同时处理多个币和暂时欠配，但不得越过 PM 与 `policy_risk` 边界
- RT 可以就“风向变了、当前难以下手、目标组合今天不适配”向 PM 发起升级或拉扯，PM 可以接受，也可以维持原判
- 但这种升级必须通过正式执行提交里的根级 `pm_recheck_requested / pm_recheck_reason` 表达，不能靠无穷无尽的 `wait` 批次偷渡
- RT 发起策略级升级的标准固定为：其判断当前市场已使 PM 现有策略不再适用
- RT 是特殊 Agent：默认没有长期记忆，不通过 `memory_assets` 管理记忆，也不启用 recall
- RT 的 learning 只在 `Chief` 主持的复盘场景中单独生成，不自动进入日常执行上下文
- RT 的复盘 learning 通过 `/self-improving-agent` 单独记录到 `.learnings/risk_trader.md`，不与其他 Agent 混写
- 在 retro 结束并收到 Chief 的会后要求后，RT 必须在自己的 session 内完成这次 learning 更新，不能由 Chief 或 AG 代写
- RT 的最小运行记录必须存在，但归 `Trade Gateway.execution` 的执行流水所有，不算 RT 的记忆
- RT 的 execution alpha 只做复盘学习账，由 `Chief` 在复盘场景中展示，不做实时奖金账，也不进入 RT 日常上下文
- RT 不直接逐模块拉数据，也不直接碰 MQ；它只拉一次 `agent_gateway` 角色包
- RT 看到的 `current_position_share_pct_of_exposure_budget`、PM 给出的 `target_exposure_band_pct` / `rt_discretion_band_pct`、以及自己提交的 `size_pct_of_exposure_budget`，统一按 `total_equity_usd * max_leverage` 的 exposure budget 口径理解
- 若 runtime pack 中存在 `latest_rt_trigger_event`，RT 必须先阅读它，把它当成“为什么现在被叫醒”的上下文，但最终交易动作仍需服从 PM mandate 与 `policy_risk`
- 若 runtime pack 中存在 `latest_risk_brake_event`，RT 必须先阅读它，把它当成“系统已经替 desk 做了什么风险动作”的上下文
- 在 `reduce_only` 风险锁下，RT 只允许继续 `reduce / close / hold / wait`
- 在 `flat_only` 风险锁下，RT 只允许 `close / hold / wait`

## 7. 待后续讨论

- 执行流水与复盘学习账的最终展示格式
