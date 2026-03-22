# 规格质量检查清单：Memory Assets

**Purpose**：验证真实资产真相源与 MEA 记忆边界  
**Created**：2026-03-15  
**Feature**：[spec.md](specs/modules/memory_assets/spec.md)

- [x] 已明确除 `learning` 外的统一真相源
- [x] 已明确 `MEA` 事件记忆唯一真相源
- [x] 已明确 PM 不自管长期记忆
- [x] 已明确各 Agent 的 learning 固定按 `.learnings/<agent>.md` 独立存放，不进入 `memory_assets`
- [x] 已明确 OpenClaw 原生记忆只是只读投影
- [x] 已明确 PM 策略资产包含每币 RT 执行边界字段
- [x] 已明确市场运行快照只保留 `15m` 轻快照与关键节点全量快照
