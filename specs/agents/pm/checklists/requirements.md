# 规格质量检查清单：PM

**Purpose**：验证 PM 的真实岗位职责与提交通道  
**Created**：2026-03-15  
**Feature**：[spec.md](specs/agents/pm/spec.md)

- [x] 已明确 `UTC 01:00` 与 `UTC 13:00` 固定策略判断班次
- [x] 已明确正式提交为 `strategy` JSON
- [x] 已明确 PM 不做硬风控和逐笔审批
- [x] 已明确 PM 不自管长期记忆
- [x] 已明确 PM 即使维持原判也直接刷新为新策略版本
- [x] 已明确 PM 的复盘 learning 固定写入 `.learnings/pm.md`
- [x] 已明确每币 `rt_discretion_band_pct` 属于 PM 正式策略约束
