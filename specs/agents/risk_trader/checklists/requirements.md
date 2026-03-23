# 规格质量检查清单：Risk Trader

**Purpose**：验证 RT 不是审核器而是执行判断者  
**Created**：2026-03-15  
**Feature**：[spec.md](specs/agents/risk_trader/spec.md)

- [x] 已明确正式提交为 JSON `ExecutionDecision`
- [x] 已明确不是 approve/reject 审核器
- [x] 已明确 `MEA` 的 `high` 级事件会直接提醒 `RT`
- [x] 已明确 RT 必须遵守 PM 给出的 `target_exposure_band_pct` 与 `rt_discretion_band_pct`
- [x] 已明确 RT 采用固定的三段式阅读顺序，而不是平铺读取所有信息
- [x] 已明确 RT 默认固定 `10` 分钟一轮，并支持重大事件立即触发
- [x] 已明确 RT 默认不使用长期记忆或 recall，learning 只在复盘时单独生成
- [x] 已明确 RT 的复盘 learning 固定写入 `.learnings/risk_trader.md`
- [x] 已明确 RT 一次正式提交可以包含多币短执行批次
- [x] 已明确最小执行流水归 `Trade Gateway.execution`，不算 RT 记忆
- [x] 已明确 execution alpha 只做复盘学习账
