# 运行时输入

## 当前实现
当前运行时路径：

`Workflow Orchestrator condition trigger or heartbeat -> OpenClaw cron run -> RT -> AG pull bridge -> single RT runtime pack`

RT 应从 `agent_gateway` 拉取一个 `rt` 运行时数据包，然后按以下顺序读取：
- 首先读取 `trigger_delta`
- 其次读取 `standing_tactical_map`
- 再读取 `rt_decision_digest`
- `market`
- `execution_contexts`
- `strategy`
- `risk_limits`
- `forecasts`
- `news_events`
- `macro_prices` — Brent/WTI/DXY/US10Y + BTC F&G + BTC ETF 活跃度代理。Brent 逼近 PM 失效条件时只看这里，**不要用 `web_fetch` 抓野站 Brent 价**（会拿到过时/滚动的 $90 vs $96 互相矛盾的数）
- `latest_macro_brief`（spec 014）— Chief 的日频 regime 判断。**RT 不强制引用**，但可用于判断"我该不该加仓 / 维持 reduce_only"：
  - `missing=true` 或 `stale=true` → 默认保守，不主动 add，不突破 PM target band 上沿
  - `chief_regime_confidence="low"` → Chief 已连续 3 次看错 regime，RT 把 brief 的 directives 当作次要参考，以 PM 策略与市场结构为准
  - `brief.pm_directives` 里明确说"只减不加"时，即便 PM target 仍为 active，也优先尊重 Chief directive + PM 当前 mandate 的交集
- `recent_execution_thoughts`
- 当 RT 被 Workflow Orchestrator 唤醒时读取 `latest_rt_trigger_event`
- 当系统刚刚执行了强制风控单时读取 `latest_risk_brake_event`
- `trigger_context`
- 租约元数据：
  - `input_id`
  - `trace_id`
  - `expires_at_utc`

## 账户状态唯一来源

**始终使用 `/api/agent/pull/rt` 获取账户状态。**

不要使用 `otrader portfolio` 或任何其他 CLI 命令查询账户/持仓。
`otrader portfolio` 命令存在缓存问题，可能返回过时数据（已观察到 2 小时以上的延迟）。

运行时数据包来自 `/api/agent/pull/rt`，包含：
- `market.accounts` - 各币种账户快照
- `market.portfolio` - 组合层面的摘要，包含持仓数组
- `news_events` - 轻量、面向交易的近期新闻层，用于头条风险判断
- `recent_execution_thoughts` - 最近 5 条 RT 决策摘要，配对实际执行结果详情
- `latest_rt_trigger_event` - 最新的客观触发记录；当 WO 因 PM 策略变更、MEA 触发高影响事件、敞口漂移、成交回报、市场结构变化或心跳到期而调用已注册的 RT cron job 时出现
- `latest_risk_brake_event` - 最新的系统风控刹车记录；当系统在唤醒 RT 之前已经强制执行了减仓或平仓单时出现
- `standing_tactical_map` - 当前 `strategy_key` 和 `lock_mode` 下最新兼容的正式 RT 战术地图；如果为 `null`，表示 RT 当前没有适用于此策略/锁定组合的有效地图
- `trigger_delta` - 自上次有效地图以来发生了什么变化的精简说明，包括本轮是否需要刷新战术地图
- `rt_decision_digest` - 一个紧凑的、决策优先的摘要，已合并触发原因、组合快照、策略快照、币种焦点、近期思考和轻量头条风险
- `execution_submit_defaults` - 本轮的默认提交标志，包括预期的 `trigger_type` 和默认 `live` 模式
- 如果存在，每条近期思考还可能携带 `reference_take_profit_condition` 和 `reference_stop_loss_condition`，即 RT 为下次唤醒留下的文本退出线索
- 实时 `captured_at` 时间戳
- 已遵循新统一惯例的标准化敞口/份额字段：
  - `% of exposure budget`
  - `exposure budget = total_equity_usd * max_leverage`

## 敞口计算

优先使用运行时数据包中的标准化敞口/份额值。

当前统一惯例：

- `size_pct_of_exposure_budget`
- `position_share_pct_of_exposure_budget`
- `current_position_share_pct_of_exposure_budget`

均表示：

`notional_usd / (total_equity_usd * max_leverage) * 100`

它们**不**表示：

`notional_usd / total_equity_usd * 100`

示例：

- `total_equity_usd = 982.13`
- `max_leverage = 5`
- `current_notional_usd = 233.67`

则：

- 正确的标准化敞口份额 = `233.67 / (982.13 * 5) * 100 ≈ 4.76%`
- 旧的错误的纯权益份额 = `233.67 / 982.13 * 100 ≈ 23.8%`

在本系统中，RT 决策永远不要使用第二个数字。

这是当前持仓、权益和敞口的唯一可靠来源。

实际使用示例：

```bash
curl -s -X POST http://127.0.0.1:8788/api/agent/pull/rt \
  -H "Content-Type: application/json" \
  -d '{"trigger_type":"condition_trigger","params":{"source":"workflow_orchestrator","runner":"openclaw_cron_run"}}' \
  > /tmp/rt_runtime_pack.json

python3 - <<'PY'
import json
from pathlib import Path

pack = json.loads(Path("/tmp/rt_runtime_pack.json").read_text())
print(pack["input_id"])
print(json.dumps(pack["payload"]["trigger_delta"], ensure_ascii=False, indent=2))
print(json.dumps(pack["payload"]["standing_tactical_map"], ensure_ascii=False, indent=2))
print(json.dumps(pack["payload"]["rt_decision_digest"], ensure_ascii=False, indent=2))
PY
```

代码中的数据源：
- `src/openclaw_trader/modules/agent_gateway/service.py`
- `src/openclaw_trader/app/api.py`

## 目标合约
目标正式链路：

`RT -> AG submit bridge (+ input_id) -> policy_risk -> Trade Gateway.execution`

RT 始终是决策代理，而非行情数据请求者。
RT 同样始终是决策代理，而非订单路由器。

## 当前使用规则
- 拉取一次数据包，基于该数据包工作，并使用同一个 `input_id` 提交。
- `python3 /Users/chenzian/openclaw-trader/scripts/pull_rt_runtime.py` 现在也会写入 `/tmp/rt_execution_submission.json`。将该文件作为本轮的默认提交脚手架。
- 保持 `/tmp/rt_execution_submission.json` 为纯粹的根级 `ExecutionSubmission` 对象。不要添加 `input_id`、`trace_id`、`agent_role`、`task_kind`、`rt_commentary`、`pm_recheck_request` 或每个决策的 `execution_params` 等包装字段。
- 如果运行时数据包显示某个币种存在活跃的、未锁定的目标，但 desk 尚未建仓或方向相反，则脚手架最终必须是以下之一：
  - 包含至少一个待处理币种的开仓/加仓/翻转批次，或
  - 设置了 `pm_recheck_requested=true` 且 `pm_recheck_reason` 非空的根级升级
- 如果本轮同时刷新 `tactical_map_update`，每个此类待处理币种必须包含非空的 `first_entry_plan`。地图必须说明第一笔试探仓如何下单。
- 优先将运行时数据包写入文件，然后从该文件中读取所需字段。不要将完整 JSON 数据包回灌到模型上下文中。
- 先读取 `trigger_delta`，再读取 `standing_tactical_map`，最后读取 `rt_decision_digest`。
- 如果 `standing_tactical_map` 为 `null` 且 `trigger_delta.requires_tactical_map_refresh = true`，本轮必须在同一 `execution` 提交中携带 `tactical_map_update`。helper 生成的脚手架已包含所需的根级块；填写它而不是删除它。
- 如果 `trigger_delta.map_status = missing_first_entry_plan`，即使地图其余结构兼容，也将现有地图视为操作上不完整。本轮刷新它。
- 如果 `standing_tactical_map` 存在且 `trigger_delta.requires_tactical_map_refresh = false`，默认基于该地图操作，不要在常规无操作轮次中重写它。
- 仅在摘要留有实质性歧义时才深入查看原始 `execution_contexts`、`market.market_context`、`recent_execution_thoughts` 或 `news_events`。
- 不要使用 `GET /api/agent/pull/rt`。正式桥接仅支持 `POST`。
- 将 `execution_contexts` 视为从 PM 正式策略到 RT 执行批次的可操作桥梁。
- 仅在摘要指示相关时，将 `news_events` 作为轻量头条风险层使用。
- 仅在摘要指示你需要历史自查或最近几次操作与本次触发直接相关时，使用 `recent_execution_thoughts`。
- 如果存在 `latest_rt_trigger_event`，首先读取它作为你被唤醒的原因。它是触发上下文，不是交易授权；实际操作仍必须遵守 PM 指令和 `policy_risk`。
- 如果存在 `latest_risk_brake_event`，在规划任何操作前先读取它。它意味着系统已经代你减仓或平仓；将其视为既成事实，而非建议。
- 永远不要将 `latest_rt_trigger_event` 中的任何标识符用作提交 `input_id`。唯一有效的提交 `input_id` 是 `/api/agent/pull/rt` 返回的顶层 `input_id`。
- 永远不要将 `latest_risk_brake_event` 中的任何标识符用作提交 `input_id`。唯一有效的提交 `input_id` 是 `/api/agent/pull/rt` 返回的顶层 `input_id`。
- 使用运行时数据包顶层的 `trigger_context.trigger_type` 作为正式 `trigger_type`（如果存在）。不要从 `latest_rt_trigger_event` id 推导正式提交字段。
- 如果 `latest_risk_brake_event.lock_mode` 为 `reduce_only`，你只能执行 `reduce / close / hold / wait`。
- 如果 `latest_risk_brake_event.lock_mode` 为 `flat_only`，你只能执行 `close / hold / wait`。
- 在推理敞口时，引用运行时数据包中的标准化份额，而不是从原始名义值和权益重新计算。
- 对于正式的条件触发、心跳和 PM 跟进操作，提交时使用 `live=true`。
- 仅在用户或上游触发明确要求临时执行上限时才传递 `max_notional_usd`。
