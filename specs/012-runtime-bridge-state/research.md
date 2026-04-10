# 调研记录：Runtime Bridge State

## 为什么不把 runtime pack 做成实时对象

- agent 拿到 `input_id` 后，应该看到稳定的事实快照
- 如果 pack 在同一轮中途自动变化，会破坏：
  - lease 语义
  - 复盘可解释性
  - submit 时的上下文一致性

结论：
- **实时的是聚合层**
- **不可变的是 runtime pack**

## 当前瓶颈

- `pull/rt` / `pull/pm` 当前在热路径里现场读取：
  - market
  - news
  - forecasts
  - latest_strategy
  - prior_risk_state
  - macro_memory
- 本地实测单次通常在 20 秒以上

## 设计选择

### 选择 A：后台聚合层 + 不可变快照 pack

优点：
- 保留 agent-first 与 lease 语义
- 显著缩短热路径
- 回退路径简单

缺点：
- 需要额外后台刷新器
- 需要处理“过期但仍可用”的语义

### 不选：让 pack 本身实时变化

原因：
- 会破坏本轮上下文一致性
- 不利于追责与复盘

## 第一版刷新策略

- 采用“定时刷新 + pull 热路径回退”
- 不要求第一版就做完全事件驱动
- 动态性最强的字段仍放在热路径补齐：
  - `latest_rt_trigger_event`
  - `latest_risk_brake_event`
  - `standing_tactical_map`
  - `trigger_delta`
