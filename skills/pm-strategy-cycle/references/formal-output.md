# 正式输出

提交前，请打开并严格遵循此 schema：
- `specs/modules/agent_gateway/contracts/strategy.schema.json`

提示词合约参考：
- `specs/modules/agent_gateway/contracts/strategy.prompt.md`

重要字段（每次都必须考虑）：
- `portfolio_mode`
- `target_gross_exposure_band_pct`
- `portfolio_thesis`
- `portfolio_invalidation`
- `flip_triggers`
- `change_summary`
- `targets[]`
- `target_exposure_band_pct`
- `rt_discretion_band_pct`
- `scheduled_rechecks[]`

规则：
- 正式提交必须是且仅是一个 JSON 对象。
- 保留运行时包中的 `input_id`，并在提交桥接调用时一并发送。
- 仅输出 JSON。不要输出 markdown 围栏、注释、要点列表、标题或尾部文本。
- 如需思考或解释，在正式提交步骤之前完成，而非在提交内容本身中。
- 即使判断未变，仍需发出一份新的策略提交。
- 不要添加执行战术，如订单类型、订单数量或入场路径。
- `flip_triggers` 是一个专用必填字段。用它来阐述什么具体条件能够证明方向性偏向的翻转——从做多到做空、从做空到做多、或从主动持仓到平仓/仅减仓。
- `targets` 必须恰好包含 2 个条目，且必须始终覆盖 `BTC` 和 `ETH`。
- 如果某币种不活跃，仍需显式包含，设置 `state = watch` 或 `disabled` 并标记平仓方向。不要省略符号。
- 将所有敞口百分比视为 `占敞口预算的百分比`，其中敞口预算 = `total_equity_usd * max_leverage`。
- 在此内部约定下，归一化总敞口和归一化单品种敞口不应超过 `100%`。
- 如果你描述当前敞口大于 `100%`，你几乎可以确定使用了错误的分母（`原始名义值 / 权益`），而非内部分母（`权益 * 最大杠杆`）。
- 在行文中描述当前总敞口或当前持仓份额时，优先使用运行时包中已有的归一化值。不要从原始的 `total_exposure_usd / total_equity_usd` 重新计算。
- 不要输出 `strategy_id`、`strategy_day_utc`、`generated_at_utc`、`trigger_type` 或任何来源引用字段。系统会在后续自动添加。
- 不要在普通策略提交中添加 `speaker_role`。

提交桥接：

```bash
curl -s -X POST http://127.0.0.1:8788/api/agent/submit/strategy \
  -H "Content-Type: application/json" \
  -d '{
    "input_id": "input_from_pull_pack",
    "portfolio_mode": "defensive",
    "target_gross_exposure_band_pct": [0, 15],
    "portfolio_thesis": "震荡市、跟进力度弱。BTC 保持活跃，ETH 观望，维持防守直到 4h 趋势确认。",
    "portfolio_invalidation": "出现干净的 4h 放量突破，或政策/风控边界变化推翻防守立场。",
    "flip_triggers": "若 BTC 失守高时间框架突破位且 4h/12h 结构同步转空，或宏观冲击明确将制度切换到 risk-off，则从谨慎做多偏向转为防御做空偏向。",
    "change_summary": "维持防守姿态，将活跃风险收窄至 BTC，ETH 保持观望。",
    "targets": [
      {
        "symbol": "BTC",
        "state": "active",
        "direction": "long",
        "target_exposure_band_pct": [0, 10],
        "rt_discretion_band_pct": 5,
        "priority": 1
      },
      {
        "symbol": "ETH",
        "state": "watch",
        "direction": "flat",
        "target_exposure_band_pct": [0, 5],
        "rt_discretion_band_pct": 5,
        "priority": 2
      }
    ],
    "scheduled_rechecks": [
      {
        "recheck_at_utc": "2026-03-22T09:00:00Z",
        "scope": "portfolio",
        "reason": "下一个主要日内结构更新后重新评估。"
      }
    ]
  }'
```

API 兼容性说明：
- `submit/strategy` 接受两种格式：
  - 扁平提交：`{"input_id":"...","portfolio_mode":"...","..."}`
  - 包装提交：`{"input_id":"...","payload":{...strategy fields...}}`
- 推荐使用扁平提交，因为更简洁、更易于理解。

常见映射提醒：
- `portfolio_thesis`，不是 `thesis`
- `portfolio_invalidation`，不是 `invalidation`
- `flip_triggers`，不是 `regime_switch_triggers`
- `change_summary`，不是 `summary`
- `input_id` 必须原样从拉取桥接返回的值中携带回来
