# Agent 规格说明：PM

**状态**：主真相层草案  
**对应视图**：PM 策略视图  
**正式提交**：`strategy` JSON

## 1. 真实岗位职责

PM 是组合经理/策略经理。它负责把结构化市场事实、事件记忆和硬风控边界，转成目标组合与策略版本。

## 1.1 输入

- `MEA` 沉淀到 `memory_assets` 的结构化事件与日摘要
- `MEA` 直接提醒的策略级变化
- `quant_intelligence` 的 `1h/4h/12h` 结构化市场事实
- `policy_risk` 的硬风控边界
- `Trade Gateway.market_data` 的账户、持仓、权益与可交易事实
- 上一版正式策略、未完成 `scheduled_rechecks` 和 revision 摘要
- 本次唤醒的 `trigger_context`
- 若系统刚执行过风控单，runtime pack 会包含 `latest_risk_brake_event`，说明系统刚替 desk 做了什么风险动作、涉及哪些仓位、当前风险锁是什么

## 2. 固定班次与触发

- 日切边界与 `MEA` 一致，使用 `UTC 00:00`
- 每天固定在 `UTC 01:00` 和 `UTC 13:00` 各运行一次策略判断
- 除固定班次外，仍可在 `MEA` 直接提醒、硬风控边界变化、RT 发起策略级升级或 `scheduled_recheck` 到点时额外运行
- `reduce / exit` 风控单触发后，PM 应被立即叫醒做风险重评，并在新 revision 中明确新的仓位边界与策略状态
- 固定班次可由 OpenClaw `cron` 提供；`scheduled_recheck` 与复杂额外唤醒继续由 `workflow_orchestrator` 协调
- 所有 PM 唤醒都必须落成可审计的触发类型，当前统一使用：
  - `pm_main_cron`：固定 `pm-main` 班次
  - `scheduled_recheck`：PM 自己在上一版策略中预定的重看时间到点
  - `risk_brake`：系统风控刹车后的风险重评唤醒
  - `agent_message`：RT / MEA / Chief / owner 通过 `sessions_send` 发起的消息唤醒
  - `manual`：人工临时重跑
  - `pm_unspecified`：来源未明但被系统明确标记为未知，禁止继续混入模糊的 `daily_main`

## 3. 可直接沟通对象

- `Macro & Event Analyst`
- `Risk Trader`
- `Crypto Chief`

## 4. 正式提交通道

- 正式提交为 `strategy` JSON
- PM 被 OpenClaw `cron` 或客观事件唤醒后，先向 `agent_gateway` 拉取一次 `pm` runtime pack
- PM 使用单次 runtime pack 内的 `input_id` 完成这次判断与正式提交
- 通过 `agent_gateway` 按 `strategy.schema.json` 校验后进入正式处理链
- `memory_assets` 负责把 PM authored `strategy` JSON 补全成 canonical 正式策略资产
- `workflow_orchestrator` 只消费 `scheduled_rechecks[]` 并在收到新策略后触发一次 RT 决策
- 新的 PM strategy revision 会释放对应作用域上的 `reduce_only / flat_only` 风险锁
- 每个 `target` 除目标暴露外，还要显式给出 `rt_discretion_band_pct`
- 所有持仓/暴露相关百分比统一按 `total_equity_usd * max_leverage` 的 exposure budget 口径表达，不按裸权益表达

## 5. 禁止事项

- 不负责硬风控规则制定
- 不负责逐笔执行时机和直接下单
- 不负责 owner 日常沟通和复盘主持

## 6. 当前已定

- 单币目标仓位为 `0` 是常态；整组 `0` 是明确防守状态，不是默认空白
- PM 可以在策略层面给出 no-initiate/only-reduce 语义，但不做逐笔审批
- PM 输出的是目标状态，不是执行路径
- PM 即使维持原判，也直接刷新出一版新的正式策略版本；不额外引入 `reaffirmed` 或 `no_material_change` 特殊提交类型
- PM 通过每币 `rt_discretion_band_pct` 给 RT 留有限执行自由度
- RT 可以在执行层面向 PM 发起升级或拉扯，但 PM 可以维持原判
- RT 发起策略级升级的标准固定为：其判断当前市场已使 PM 现有策略不再适用
- PM 不自管长期记忆；正式记忆由 `memory_assets` 托管
- PM 不负责生成正式策略资产的系统字段；`strategy_id`、`strategy_day_utc`、`generated_at_utc`、`trigger_type` 由系统补齐
- PM 不直接逐模块拉数据，也不直接碰事件总线实现细节；它只拉一次 `agent_gateway` 角色包
- PM 的复盘 learning 通过 `/self-improving-agent` 单独记录到 `.learnings/pm.md`，不与其他 Agent 混写
- 在 retro 结束并收到 Chief 的会后要求后，PM 必须在自己的 session 内完成这次 learning 更新，不能由 Chief 或 AG 代写

## 7. 待后续讨论

- PM revision 与 `scheduled_recheck` 的最终字段约束
