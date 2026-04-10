# 数据模型：Runtime Bridge State

## 1. RuntimeBridgeState

中文：运行态聚合快照

字段：
- `state_id`
- `refreshed_at_utc`
- `refresh_reason`
- `source_timestamps`
- `context`
- `runtime_inputs`

说明：
- `context` 保存聚合后的基础上下文
- `runtime_inputs` 保存各角色基础 payload，不含 lease 和动态附加字段

## 2. RuntimeBridgeContext

字段：
- `market`
- `news`
- `forecasts`
- `latest_strategy`
- `macro_memory`
- `policies`

说明：
- 这是 `build_runtime_inputs(...)` 的上游基础输入

## 3. RuntimeBridgePayload

字段：
- `task_kind`
- `payload`

说明：
- `payload` 是某角色的基础 runtime payload
- 不包含：
  - `input_id`
  - `expires_at_utc`
  - 角色专属动态补丁

## 4. RuntimeBridgeSnapshotSource

字段：
- `source`
  - `cache`
  - `stale_cache`
  - `direct_fallback`
- `refreshed_at_utc`
- `age_seconds`

说明：
- 仅用于说明本次 `pull/*` 是从哪里切出来的
