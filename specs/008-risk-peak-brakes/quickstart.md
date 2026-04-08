# Quickstart：风控峰值刹车与双触发闭环

1. 在配置中开启风控峰值刹车监控器。
2. 保持现有 `pm-main` 和 `rt-15m` OpenClaw cron job 可运行。
3. 当单仓或组合达到 `reduce` / `exit` 阈值时：
   - 系统自动执行风险单
   - RT 立即被唤醒进行风险复查
   - PM 同时被唤醒进行策略重评
4. PM 新 strategy revision 落库后，RT 会再次通过现有 `pm_strategy_update` 链自然触发。

