# Quickstart：Memory Assets

## 场景 1：收口 MEA 正式事件

1. 接收 `MEA` 的结构化事件提交
2. 产出或更新 `MacroEventRecord`
3. 更新对应 `MacroDailyMemory`

## 场景 2：收口 PM 正式策略

1. 接收 AG 校验通过的 `strategy` 正式提交
2. 写入完整 `StrategyAsset`
3. 维护 supersedes 和 recheck 引用

## 场景 3：生成记忆投影

1. 选择需要召回的正式资产
2. 生成 `MemoryProjection`
3. 同步到只读语义召回层

## 验收要点

- 原始新闻不进入长期真相源
- transcript 不形成正式资产
- 其他 Agent 读取的是 `memory_assets` 中的正式事件与策略记忆
