# 实施计划：Runtime Bridge State

## 1. 目标

把 `agent_gateway` 当前“现场 fan-in + 现场切包”的热路径，拆成：

1. 后台持续更新 `runtime_bridge_state`
2. `pull/*` 默认读取 `runtime_bridge_state`
3. `pull/*` 只在快照缺失或超龄时，回退到现场 fan-in

## 2. 实施范围

- 新增运行态聚合刷新器
- 新增 `runtime_bridge_state` 状态资产
- `pull/rt` / `pull/pm` / `pull/mea` / `pull/chief` 改为优先使用聚合快照
- 运行配置增加：
  - 是否启用聚合刷新
  - 刷新间隔
  - 快照允许年龄

## 3. 实现步骤

### 第一步：规格与数据模型
- 新增 `specs/012-runtime-bridge-state/*`
- 锁定：
  - `runtime_bridge_state` 字段
  - 缓存/过期/回退语义
  - 动态字段仍由热路径补齐

### 第二步：状态资产与刷新器
- 在 `state_memory` 中增加 `RuntimeBridgeState`
- 新增后台 `RuntimeBridgeMonitor`
- 周期性刷新 market/news/forecast/strategy/risk/macro，并写入状态资产

### 第三步：agent_gateway 接入
- `pull/*` 先尝试读取最新 `runtime_bridge_state`
- 命中后直接切出角色基础 payload
- 保留：
  - 新 `input_id`
  - 新 `trace_id`
  - 新 lease
  - RT/PM 的动态附加字段

### 第四步：测试与实验
- 回归：
  - `tests.test_v2_agent_gateway`
  - `tests.test_v2_workflow_orchestrator`
  - 必要时补 `tests.test_v2_api_integration`
- live 实验：
  - 触发一次真实 RT cron
  - 观察 pack 来源、耗时、行为链是否收口

## 4. 风险与回退

- 聚合刷新失败：回退到旧的现场 fan-in
- 聚合状态过旧：优先尝试同步刷新；失败时允许使用最后一份可用状态或直接回退
- 不引入“动态变化 pack”，避免破坏 lease 语义
