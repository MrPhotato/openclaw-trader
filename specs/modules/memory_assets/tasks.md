# 任务分解：Memory Assets

**规格文档**：`specs/modules/memory_assets/spec.md`

## 第一波：主规格收口

- [ ] T001 固化除 `learning` 外所有真实资产统一进入 `memory_assets`
- [ ] T002 固化 `MEA` 事件记忆、PM 正式策略资产、日摘要和投影边界

## 第二波：重点契约

- [ ] T003 定义 `MacroEventRecord`、`MacroDailyMemory`、`StrategyAsset`、`MemoryProjection` 的资产边界
- [ ] T004 记录真实资产写入前提和 transcript 排除规则

## 第三波：迁移对齐

- [ ] T005 在旧 `007` 和总览文档中统一迁移说明
- [ ] T006 清理“MEA 私有记忆”与“原生记忆双写”残留表述
