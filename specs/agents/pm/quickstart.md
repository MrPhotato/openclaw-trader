# Quickstart：PM

1. 读取 `memory_assets` 中的事件真相、上一版正式策略和未完成 recheck。
2. 读取 `quant_intelligence` 的 `1h/4h/12h` 结构化市场事实。
3. 读取 `policy_risk` 和 `Trade Gateway.market_data` 的边界与账户事实。
4. 在 `UTC 01:00` 或 `UTC 13:00` 的固定班次，或额外事件触发下，形成目标组合、每币 `rt_discretion_band_pct` / `no_new_risk` 和 `scheduled_rechecks[]`。固定班次可由 OpenClaw `cron` 提供。
5. 提交 `strategy` JSON 给 `agent_gateway`。
6. `memory_assets` 持久化完整正式策略，`workflow_orchestrator` 提取 recheck 并触发一次 RT 决策；复杂 recheck 调度继续由 `workflow_orchestrator` 管理。

## 关键约束

- PM 不输出执行路径
- PM 不直接写长期记忆
- PM 不绕过 AG 直接提交正式资产
