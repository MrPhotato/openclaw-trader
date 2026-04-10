# Quickstart：Runtime Bridge State

## 目标

验证 `pull/rt` / `pull/pm` 是否已经改成：
- 默认从 `runtime_bridge_state` 切包
- 缺失或过期时自动回退

## 步骤

1. 启用运行态聚合刷新
2. 重启本地 API 宿主
3. 等待后台刷新器写出至少一条 `runtime_bridge_state`
4. 分别调用：
   - `POST /api/agent/pull/rt`
   - `POST /api/agent/pull/pm`
5. 检查 pack 中是否带有：
   - `runtime_bridge_state.source`
   - `runtime_bridge_state.refreshed_at_utc`
6. 人为让聚合状态缺失或过期，再次调用 `pull/*`
7. 确认系统仍能通过回退路径正常返回
