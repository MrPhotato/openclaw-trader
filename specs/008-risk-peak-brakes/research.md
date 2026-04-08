# 研究记录：风控峰值刹车与双触发闭环

- 当前 `policy_risk` 的单仓风控是“入场价 -> 当前价”的 adverse move，不会捕捉“先浮盈后回吐”的情况。
- 当前没有“组合从当日高点回撤”的硬风控，因此多个相关仓位一起小幅回撤时，账户可能从盘中高点明显回落，但不会自动触发系统动作。
- `workflow_orchestrator/rt_trigger.py` 已经验证了 `openclaw cron run <job_id>` 这条路径可用，因此本功能应复用同样的桥接方式去触发 `pm-main` 和 RT。
- `trade_gateway.execution` 已经有统一的 `ExecutionDecision -> ExecutionPlan -> ExecutionResult` 执行链，系统风控单不应旁路。
- 当前 RT 已经改为条件触发模式，RT 第一轮风险复查只需要理解系统已执行了什么，不需要重新承担第一反应。

