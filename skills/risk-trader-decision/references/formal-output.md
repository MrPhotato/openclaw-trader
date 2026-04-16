# 正式输出

提交前，请打开并严格遵循以下 schema：
- `specs/modules/agent_gateway/contracts/execution.schema.json`

Prompt 合约参考：
- `specs/modules/agent_gateway/contracts/execution.prompt.md`

## 期望输出格式
- 恰好一个 JSON 对象
- 保留运行时数据包中的 `input_id`，并在提交桥接调用中发送
- 保留运行时数据包 `trigger_context` 中的 `trigger_type`（如果存在）；否则使用明确的值如 `condition_trigger`
- 仅输出 JSON；不要输出 markdown 围栏、散文、标题或尾部备注
- 一次提交可以包含多币种的 `decisions[]`
- 当本轮改变了 RT 的战术计划，或 `trigger_delta.requires_tactical_map_refresh = true` 时，包含根级 `tactical_map_update`
- 将 `decisions[]` 放在提交对象的根级
- **不要**将批次包裹在 `execution`、`payload.execution`、`result` 或其他嵌套键下
- 如果你决定本轮不操作，仅在没有活跃的未锁定入场缺口时，或在你同时通过根级 PM recheck 升级时，提交显式的根级 `"decisions": []` 空批次
- 如果 PM 在某币种上有活跃的、未锁定的目标，而 desk 尚未建仓或方向相反，全部 `wait` / 空批次是无效的，除非你同时设置根级 `pm_recheck_requested=true` 并提供非空 `pm_recheck_reason`
- 如果 `tactical_map_update` 覆盖了一个活跃的、未锁定且 desk 尚未建仓或方向相反的币种，该币种块必须包含非空的 `first_entry_plan`

## 规则
- 可选的 action 包括：
  - `open`
  - `add`
  - `reduce`
  - `close`
  - `wait`
  - `hold`
- 使用 `size_pct_of_exposure_budget` 表达 `% of exposure budget`，其中 exposure budget = `total_equity_usd * max_leverage`
- 在 `reason` 中描述当前敞口时，使用相同的 `% of exposure budget` 惯例
- 不要使用旧的 `% of equity` 分母描述敞口
- 当你有活跃或新调整的仓位时，优先留下简短的可选 `reference_take_profit_condition` 备注供下次 RT 唤醒使用
- 当你有活跃或新调整的仓位时，优先留下简短的可选 `reference_stop_loss_condition` 备注供下次 RT 唤醒使用
- `reference_take_profit_condition` 仅为文本记忆辅助；它不会创建订单，也不会绕过下游风控/执行逻辑
- `reference_stop_loss_condition` 同样仅为文本记忆辅助；它不会创建订单，也不会绕过下游风控/执行逻辑
- `pm_recheck_requested` 和 `pm_recheck_reason` 是根级升级字段。当 PM 当前指令过于矛盾或约束过紧以至于无法负责任地执行时使用。

RT 不能自行批准自己。
正式提交后，风控审批在下游进行。

## 提交桥接

正式的条件触发、心跳和 PM 跟进操作的桥接调用：

### Helper 用法

```bash
python3 /Users/chenzian/openclaw-trader/scripts/pull_rt_runtime.py
# 原地编辑 /tmp/rt_execution_submission.json，然后提交
python3 /Users/chenzian/openclaw-trader/scripts/submit_rt_decision.py \
  --input-id "input_from_pull_pack" \
  --payload-file /tmp/rt_execution_submission.json \
  --live
```

Helper 提醒：
- `/tmp/rt_execution_submission.json` 必须仅包含根级 `ExecutionSubmission` 对象。
- **不要**将 `input_id`、`trace_id`、`agent_role`、`task_kind`、`pm_recheck_request`、`rt_commentary` 或每个决策的 `execution_params` 放入该文件。
- `submit_rt_decision.py` 会在 payload 文件之外为你添加 `input_id`、`live` 和可选的 `max_notional_usd`。

### 等效原始 HTTP 调用

```bash
curl -s -X POST http://127.0.0.1:8788/api/agent/submit/execution \
  -H "Content-Type: application/json" \
  -d '{
    "input_id": "input_from_pull_pack",
    "live": true,
    "decision_id": "decision_rt_20260322_001",
    "strategy_id": "strategy_...",
    "generated_at_utc": "2026-03-22T17:57:00Z",
    "trigger_type": "condition_trigger",
    "pm_recheck_requested": false,
    "tactical_map_update": {
      "map_refresh_reason": "pm_strategy_revision",
      "portfolio_posture": "防守偏多，优先控制追价冲动。",
      "desk_focus": "BTC 优先推进，ETH 在回踩承接位再介入。",
      "risk_bias": "若 headline risk 再升级，先减风险再联系 PM。",
      "next_review_hint": "下次重点看 BTC 回踩后的承接质量和 ETH 是否重新站回结构位。",
      "coins": [
        {
          "coin": "BTC",
          "working_posture": "回踩承接优先，避免突破后追高。",
          "base_case": "只在结构确认继续的情况下慢慢推进。",
          "first_entry_plan": "如果当前仍是无仓且 BTC 保持 active long，就先用 2% exposure budget 开第一笔试探仓，不再把等待当默认动作。",
          "preferred_add_condition": "回踩 1h 结构位后重新站稳并伴随买盘恢复。",
          "preferred_reduce_condition": "若承接失败并失守最近 pullback low，则先减回观察仓。",
          "reference_take_profit_condition": "上冲 1h 范围上沿但动能衰减时，分批收一部分。",
          "reference_stop_loss_condition": "跌破关键回踩低点且卖压扩张时，优先减仓。",
          "no_trade_zone": "突破后第一根冲高延伸里不追单。",
          "force_pm_recheck_condition": "若 headline risk 继续升级并导致 BTC / ETH 同步失守关键位，要求 PM 重评。",
          "next_focus": "观察回踩后的真实承接而不是单根上冲。"
        }
      ]
    },
    "decisions": [
      {
        "symbol": "BTC",
        "action": "open",
        "direction": "long",
        "size_pct_of_exposure_budget": 2.0,
        "priority": 1,
        "urgency": "normal",
        "valid_for_minutes": 15,
        "reason": "BTC 是唯一活跃币种，价格仍在预期入场区间内，风控限额清晰。",
        "reference_take_profit_condition": "若 BTC 触及 1h 范围上沿且动能停滞，将 2%-4% 的 exposure budget 分批止盈。",
        "reference_stop_loss_condition": "若 BTC 跌破 1h 回踩低点且抛压扩张，减仓并重新评估入场 thesis。"
      },
      {
        "symbol": "ETH",
        "action": "wait",
        "priority": 2,
        "urgency": "low",
        "valid_for_minutes": 15,
        "reason": "ETH 保持观望，本轮无更优战术动作。"
      }
    ]
  }'
```

## 可选测试/调试覆盖
- 仅在用户或上游触发明确要求临时上限时才包含 `max_notional_usd`
- 正常生产操作中不要假设默认的系统上限

## 边界提醒
- `execution` 提交是**决策层**合约，不是订单层合约。
- RT 提交的是 `decisions[]`，不是 `orders[]`。
- `tactical_map_update` 是可选的，但如果存在，必须与 `decisions[]` 并列放在根级，不能嵌套在某个 decision 项内。
- `pm_recheck_requested` 和 `pm_recheck_reason` 同样与 `decisions[]` 并列放在根级。
- 像 `{..., "execution": {"decisions": [...]}}` 这样的 payload 是无效的，会被拒绝。
- 显式空批次 `{..., "decisions": []}` 是有效的，表示"本轮不操作"。
- 但显式空批次仅在没有活跃的未锁定入场缺口时有效，或在你同时通过 `pm_recheck_requested=true` 加上具体原因进行升级时有效。
- 当 PM 仍有活跃的未锁定目标且 desk 尚未建立第一笔仓位时，`wait` 不是中性默认选项。要么下第一笔单，要么升级。
- 仅在表示"保持当前仓位不变"时使用 `hold`；它是有效的无操作，不应生成新订单。
- `reference_take_profit_condition` 和 `reference_stop_loss_condition` 是可选的。用它们为下次 RT 唤醒留下简洁的文本退出线索。
- `MARKET/LIMIT/IOC/FOK`、`order_id`、`fill_price`、`fill_size`、broker 重试和交易所保证金模式是下游关注点，在 `policy_risk` 和 `Trade Gateway.execution` 之后处理。
- 仅在用户明确要求模拟或调试时使用 `live=false`。
