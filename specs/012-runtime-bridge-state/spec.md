# 功能规格说明：Runtime Bridge State

**功能分支**：`codex/011-rt-tactical-map`  
**创建日期**：2026-04-09  
**状态**：草案  
**输入描述**：Option A: keep runtime packs as immutable snapshots, but add a continuously refreshed aggregate layer underneath so `pull/rt` and `pull/pm` stop fan-in loading every upstream module on the hot path.

## 1. 背景与目标

当前 `pull/rt` 和 `pull/pm` 仍然走“现场拼包”模式：agent gateway 在热路径里同步读取 market、news、forecast、strategy、risk、macro，再按角色压成 runtime pack。这样虽然语义正确，但每次 `pull` 都要重复做一遍 fan-in，导致本地 `pull/rt` / `pull/pm` 单次耗时经常在 20 秒以上。

Runtime pack 本身不适合做成“实时变动对象”。Agent 一旦拿到 `input_id`，该轮看到的世界就应保持稳定，否则会破坏 lease、复盘和解释性。真正需要实时的，是 runtime pack 下面的聚合层。

本功能的目标是：
- 增加一个持续刷新的 `runtime_bridge_state`
  中文：运行态聚合快照
- 让 `pull/rt`、`pull/pm`、`pull/mea`、`pull/chief` 默认从该聚合快照切出一张稳定 pack
- 只在聚合快照缺失或明显过期时，才回退到旧的现场拼包链路

## 2. 当前系统基线

- `agent_gateway._issue_runtime_pack()` 当前会直接调用 `_collect_bridge_context()`。
- `_collect_bridge_context()` 当前同步读取：
  - market
  - news
  - forecasts
  - latest_strategy
  - prior_risk_state
  - macro_memory
- 然后再调用 `build_runtime_inputs(...)` 做角色裁剪。
- 这导致 `pull/rt` / `pull/pm` 热路径承担了“实时采集 + 角色切包”两段工作。
- RT 现有的 `standing_tactical_map`、`trigger_delta`、`rt_decision_digest` 已经生效，但它们仍然建立在慢速 pull 之上。

## 3. 用户场景与验收

### 场景 1：正常 pull 直接命中运行态聚合快照

当 PM、RT、MEA、Chief 调用 `pull/*` 时，系统应优先读取最近刚刷新的 `runtime_bridge_state`，并从中生成一张稳定的 runtime pack，而不是在热路径里重新向每个上游模块发起同步读取。

**验收标准**

1. 正常情况下，`pull/rt` / `pull/pm` 默认读取 `runtime_bridge_state`，不再执行完整 fan-in。
2. runtime pack 仍然是一次性快照，拿到 `input_id` 后不会在同一轮内自行变化。

### 场景 2：聚合快照缺失或明显过期时，系统仍能回退

当后台聚合层尚未初始化、刷新失败或过期太久时，`pull/*` 不能直接失效，而应回退到旧的现场拼包链路，以保证 agent 仍然能工作。

**验收标准**

1. 若 `runtime_bridge_state` 缺失，`pull/*` 会自动回退到现场拼包。
2. 若 `runtime_bridge_state` 超过允许年龄且后台刷新失败，系统仍可使用最后一份可用状态或直接现场拼包，不允许整条 pull 断掉。

## 4. 功能需求

- **FR-001**：系统必须新增 `runtime_bridge_state`
  中文：运行态聚合快照
  作为持续刷新的状态资产，保存：
  - 聚合后的基础上下文
  - 已压缩好的各角色基础 runtime payload
  - 刷新时间与来源时间戳
- **FR-002**：`runtime_bridge_state` 必须由后台刷新器持续更新，而不是只在某个 agent pull 时被动生成。
- **FR-003**：`pull/rt`、`pull/pm`、`pull/mea`、`pull/chief` 必须默认从 `runtime_bridge_state` 生成 runtime pack。
- **FR-004**：即使读取 `runtime_bridge_state`，每次 `pull/*` 仍必须生成新的：
  - `input_id`
  - `trace_id`
  - `expires_at_utc`
  以保持 lease 语义不变。
- **FR-005**：`runtime_bridge_state` 必须至少包含这些聚合来源：
  - market
  - news
  - forecasts
  - latest_strategy
  - prior_risk_state / policies
  - macro_memory
- **FR-006**：`runtime_bridge_state` 必须至少包含这些角色基础 payload：
  - `pm`
  - `risk_trader`
  - `macro_event_analyst`
  - `crypto_chief`
- **FR-007**：即使基础 payload 来自聚合快照，`pull/rt` 仍必须继续在热路径里补动态字段，例如：
  - `latest_rt_trigger_event`
  - `latest_risk_brake_event`
  - `standing_tactical_map`
  - `trigger_delta`
  - `rt_decision_digest`
- **FR-008**：系统必须暴露 `runtime_bridge_state` 的刷新时间和快照来源，便于判断 pack 使用的是：
  - 正常缓存
  - 过期缓存
  - 现场回退

## 5. 非功能要求

- **NFR-001**：runtime pack 继续保持不可变快照语义，不得变成“实时自更新对象”。
- **NFR-002**：正常热路径下，`pull/rt` / `pull/pm` 的主要工作应退化为“读聚合状态 + 生成 lease + 补动态字段”。
- **NFR-003**：后台聚合刷新失败时不得让 `pull/*` 整体不可用。
- **NFR-004**：聚合层设计必须与现有 `state_memory`、`workflow_orchestrator` 和 `agent_gateway` 共存，不能破坏现有触发链和风控链。

## 6. 关键实体

- **RuntimeBridgeState（运行态聚合快照）**：后台刷新器维护的最新 desk 基础上下文，既包含聚合来源，也包含各角色基础 payload。
- **RuntimeBridgePayload（角色基础 payload）**：某个角色在不含 lease 与动态附加字段前的基础运行输入。
- **RuntimeBridgeSnapshotSource（快照来源）**：说明本次 pack 来自正常缓存、过期缓存还是现场回退。

## 7. 假设与约束

- runtime pack 保持不可变快照；不会被实时增量推送直接改写。
- 第一版聚合层允许以“定时刷新 + 缺失时回退”的形式实现，不要求一次性做成完全事件驱动。
- 本功能优先优化 `pull/rt` 与 `pull/pm`，但实现上仍应兼容 MEA 与 Chief。
- 这次不改变 RT/PM 的业务判断逻辑，只优化输入装配方式。

## 8. 成功标准

- **SC-001**：正常运行时，`pull/rt` / `pull/pm` 不再每次同步 fan-in 所有上游模块。
- **SC-002**：在运行态聚合快照已预热的情况下，`pull/rt` / `pull/pm` 的响应时间显著低于当前现场拼包路径。
- **SC-003**：runtime pack 仍保持稳定快照和 lease 语义，不因引入实时聚合层而破坏解释性。
- **SC-004**：聚合层不可用时，agent 仍可通过回退链路继续工作。
