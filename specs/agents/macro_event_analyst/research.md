# 研究记录：Macro & Event Analyst

## 决策 1：工作模式固定为低频巡检 + 事件驱动

- **Decision**：默认每 `2` 小时巡检一次，收到 `NEWS_BATCH_READY` 时即时唤醒并重置计时器
- **Rationale**：贴近真实岗位节奏，也避免把 MEA 变成常驻新闻广播器
- **Alternatives considered**：完全定时或完全新闻驱动；结论是两者结合更稳

## 决策 2：正式提交不保留 alert 字段

- **Decision**：`MEA` 的正式提交只有结构化事件列表，无 `alert`
- **Rationale**：提醒和追问属于协作层，不应编码进正式资产
- **Alternatives considered**：保留 `alert` 让系统继续路由；结论是会让 `workflow_orchestrator` 回到内容路由中心

## 决策 3：PM 策略影响提醒走直接沟通

- **Decision**：影响 thesis、目标仓位、recheck 或 invalidation 的信息由 `MEA` 直接提醒 `PM`
- **Rationale**：符合真实协作方式，也与“自由沟通、结构化收口”一致
- **Alternatives considered**：让 `WO` 中转提醒；结论是会增加不必要的控制面耦合

## 决策 4：记忆只读 memory_assets 投影

- **Decision**：`MEA` 的历史回忆来自 `memory_assets` 投影到原生语义记忆的只读层
- **Rationale**：保留协作体验，但不让 Agent 拿到长期记忆写权限
- **Alternatives considered**：允许 OpenClaw 自动捕获；结论是不符合真相源边界
