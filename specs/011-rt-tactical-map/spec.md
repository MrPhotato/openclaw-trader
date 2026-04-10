# 功能规格说明：RT 当班战术地图

**功能分支**：`codex/011-rt-tactical-map`  
**创建日期**：2026-04-09  
**状态**：草案  
**输入描述**：Design a standing tactical map for RT so condition-triggered runs work from a persistent trading map plus trigger delta instead of re-analyzing the whole world.

## 1. 背景与目标

当前 RT 已经从固定 15 分钟定时切到“条件触发 + heartbeat 兜底”的运行方式，但单轮决策仍然偏慢。根因不是 RT 看不到信息，而是它每次被叫醒后，仍然倾向于重新阅读大部分运行输入，再临时拼出一套新的战术理解。

真实的顶级 discretionary trader 不会每次被触发都从零开始研究世界，而是会维护一份当班战术地图：先定义当前 book 的打法、每个币的加减仓条件、明确不动作区域和何时必须找 PM 重评。盘中被叫醒时，只需要判断“这次触发与既有战术地图相比到底发生了什么变化”。

本功能的目标是：
- 给 RT 增加一份持续存在、可版本化的 `standing_tactical_map`
  中文：当班战术地图
- 给每次 RT 唤醒补一份 `trigger_delta`
  中文：本次触发增量
- 让 RT 默认按“增量 -> 地图 -> 风险锁 -> 必要时下钻”的顺序工作，而不是每轮重开世界模型

## 2. 当前系统基线

- RT 当前由 `workflow_orchestrator -> openclaw cron run <rt_job_id>` 唤醒，已经是条件触发优先、heartbeat 兜底的模式。
- `pull/rt` 已经包含：
  - `rt_decision_digest`
  - `latest_rt_trigger_event`
  - `latest_risk_brake_event`
  - `execution_contexts`
  - `recent_execution_thoughts`
  - `news_events`
- RT 已有 digest-first 提示链，但还没有一份长期存在的战术地图来承接“上一轮已经想明白的东西”。
- `state_memory` 当前能保存 strategy、execution、macro、risk brake 等资产，但没有 RT 专属的战术地图资产。
- RT 的自动触发仍应继续复用标准 cron job，不应把机器事件直接发到 RT `main` 会话。

## 3. 用户场景与验收

### 场景 1：RT 被事件触发唤醒时，先检查已有战术地图是否仍成立

当 PM 更新策略、系统风控动作、结构变化、成交回查或 heartbeat 触发 RT 时，RT 应先看到“上一次已经形成的战术打法”以及“这次到底新增了什么变化”，而不是重新读完整 runtime pack 才开始工作。

**验收标准**

1. `pull/rt` 返回结果中包含 `standing_tactical_map` 和 `trigger_delta`。
2. `trigger_delta` 能直接说明本次被叫醒的原因、风险锁、涉及币种以及相对于既有地图的关键变化。

### 场景 2：RT 在重大变化后能更新自己的战术地图

当 PM 新策略落库、系统刚执行过风险刹车、或 RT 自己刚完成重要执行动作后，RT 应能把新的交易地图持久化下来，供下一次条件触发直接复用。

**验收标准**

1. 系统支持 RT 保存或刷新最新 `standing_tactical_map`，并保留版本与更新时间。
2. 下一次 `pull/rt` 时，若仍处于同一策略语境和同一风险锁约束，RT 会优先读到这份地图而不是从零开始推导。

## 4. 功能需求

- **FR-001**：系统必须为 RT 新增 `standing_tactical_map`
  中文：当班战术地图
  作为长期资产，并通过 `state_memory` 持久化保存。
- **FR-002**：`standing_tactical_map` 必须至少包含：
  - 当前组合打法姿态
  - 当前 desk 关注点
  - 当前风险倾向
  - 每个活跃币种的战术 if/then 条件
- **FR-003**：每个币种的战术地图必须至少包含：
  - `preferred_add_condition`
    中文：优先加仓条件
  - `preferred_reduce_condition`
    中文：优先减仓条件
  - `reference_take_profit_condition`
    中文：参考止盈条件
  - `reference_stop_loss_condition`
    中文：参考止损条件
  - `no_trade_zone`
    中文：明确不动作区域
  - `force_pm_recheck_condition`
    中文：强制 PM 重评条件
- **FR-004**：系统必须为每次 RT 唤醒构建 `trigger_delta`
  中文：本次触发增量
  其内容至少包括：
  - 当前触发原因和严重度
  - 是否发生 PM 策略变化
  - 是否发生系统风控动作
  - 是否有新成交
  - 哪些币出现关键结构变化
  - 当前风险锁模式
- **FR-005**：`pull/rt` 必须把 `standing_tactical_map`、`trigger_delta` 与现有 `rt_decision_digest` 一起返回，作为 RT 默认工作入口。
- **FR-006**：系统必须定义 RT 地图刷新的标准时机，至少包括：
  - PM 新策略 revision 后
  - 系统 `reduce / exit` 风控动作后
  - RT 完成重要执行动作后
  - RT 明确判定原地图已失效时
- **FR-007**：RT 的地图更新必须与当前 `strategy_key`
  中文：策略版本键
  和当前风险锁状态绑定，以避免旧地图在新策略或新风险状态下被误复用。
- **FR-008**：自动调度入口继续使用标准 `cron run`；机器事件不得改为直接写入 RT `main` 会话，RT `main` 只用于人和 Agent 的长期协作沟通。
- **FR-009**：即使提供 `standing_tactical_map` 与 `trigger_delta`，RT 仍然可以在出现歧义时继续查看 `execution_contexts`、`market_context`、`recent_execution_thoughts`、`news_events` 等原始字段；系统不得把 RT 降级成机械执行器。

## 5. 非功能要求

- **NFR-001**：该功能必须保持 agent-first 风格；服务层只提供更好的持续记忆与增量输入，不替 RT 生成主观交易结论。
- **NFR-002**：默认读取路径必须明显缩短，正常触发轮次应优先依靠 `trigger_delta + standing_tactical_map + rt_decision_digest` 完成一轮判断。
- **NFR-003**：地图与增量输入必须与 PM 新策略、风险锁和系统风控事件保持一致，不能让 RT 在旧地图和新事实之间产生语义错位。
- **NFR-004**：地图设计必须兼容当前 `workflow_orchestrator` 条件触发、`risk_brake` 双触发闭环和现有 `pull/submit` 合约，不能破坏现有主链。

## 6. 关键实体

- **StandingTacticalMap（当班战术地图）**：RT 在当前策略语境下维护的持续战术资产，描述当前组合姿态、每个活跃币种的 if/then 条件、下一轮关注点和强制升级条件。
- **TriggerDelta（本次触发增量）**：RT 本次被叫醒时与上次稳定战术地图相比新增的关键信息，包括触发原因、策略变化、风险锁变化、成交变化和结构变化。
- **TacticalMapRefreshReason（战术地图刷新原因）**：记录地图为什么被更新，例如 PM revision、risk brake、post-trade refresh 或 RT 自主重构。

## 7. 假设与约束

- RT 的标准自动入口继续是 `workflow_orchestrator -> openclaw cron run <rt_job_id>`，不是 `main` 会话消息。
- 第一版只要求系统维护“最新有效地图”和版本化历史资产，不要求引入复杂的人类可视化编辑器。
- 地图是 RT 专属资产；PM、MEA、Chief 可以读取其摘要，但不直接代写。
- 这次只解决 RT 的持续战术上下文问题，不同时改 PM 的长期策略资产结构。

## 8. 成功标准

- **SC-001**：RT 被条件触发唤醒时，能直接从 `standing_tactical_map + trigger_delta + rt_decision_digest` 开始工作，而不是先重新推导整套盘面逻辑。
- **SC-002**：在 PM revision、risk brake 和重要执行动作之后，RT 的下一轮输入能读到与当前策略和风险锁一致的最新战术地图。
- **SC-003**：该设计在保留 RT 临场发挥自由度的同时，减少重复读取和无效工具往返，让 RT 更像持续维护交易地图的战术交易员，而不是重复分析器。
