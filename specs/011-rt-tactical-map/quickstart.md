# Quickstart：RT 当班战术地图

1. 保持现有 RT 自动入口不变，继续由 `workflow_orchestrator -> openclaw cron run <rt_job_id>` 唤醒 RT。
2. 当 `pull/rt` 被调用时，系统返回：
   - `rt_decision_digest`
   - `standing_tactical_map`
   - `trigger_delta`
   - 原始 drill-down 数据
3. RT 默认工作顺序改成：
   - 先看 `trigger_delta`
   - 再看 `standing_tactical_map`
   - 再看风险锁
   - 只有歧义时才下钻原始上下文
4. 当 PM revision、risk brake 或 RT 重要动作发生后，RT 会刷新自己的 `standing_tactical_map`。
5. 下一次事件触发时，RT 直接在旧地图基础上判断“这次到底变了什么”，而不是从零开始推导。
