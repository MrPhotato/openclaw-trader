# 模块主规格索引

本目录是新的模块级主真相层。  
旧的 `specs/001-007` 继续保留，但主要承担迁移波次、横切约束和历史背景，不再单独充当模块边界的最高真相源。

## 9 个模块

| 模块 | 目录 | 当前深度 | 记录重点 |
| --- | --- | --- | --- |
| Trade Gateway | `specs/modules/trade_gateway` | 完整套件 | 统一交易所边界、`market_data`/`execution` 子域、事实读取与执行交付 |
| News Events | `specs/modules/news_events` | 完整套件 | 固定源轮询、轻去重、新闻批次、`NEWS_BATCH_READY` |
| Quant Intelligence | `specs/modules/quant_intelligence` | `spec` | `1h/4h/12h` 计算与结构化市场事实 |
| Policy Risk | `specs/modules/policy_risk` | `spec` | 硬风控边界、冷却、panic exit、breaker |
| Workflow Orchestrator | `specs/modules/workflow_orchestrator` | 完整套件 | 客观唤醒、生命周期、MEA 计时器、正式收口 |
| Agent Gateway | `specs/modules/agent_gateway` | 完整套件 | OpenClaw 协作层、三类正式提交模板、准入校验与分发 |
| Memory Assets | `specs/modules/memory_assets` | 完整套件 | 真实资产真相源、MEA 事件记忆、PM 策略资产、记忆投影 |
| Notification Service | `specs/modules/notification_service` | `spec` | 确定性通知命令、投递结果、去重 |
| Replay Frontend | `specs/modules/replay_frontend` | `spec` | 统一读模型、回放查询、前端订阅面 |

## 使用规则

- 后续讨论模块边界时，优先更新本目录，再决定是否回写旧 feature specs。
- 模块 `spec.md` 统一记录：职责、拥有资产、输入、输出、直接协作边界、不负责什么、当前已定、待后续讨论。
- 重点 full-suite 模块的 `plan/data-model/tasks/contracts` 必须与 `spec.md` 保持一致。
- 当前实现里的 Python 包 `state_memory` 对应模块名 `Memory Assets`；后续模块命名以 `Memory Assets` 为准，不再把 `state_memory` 当作对外模块名。
- `strategy_intent` 与 `context_builder` 属于历史迁移残留，不再视为活跃模块边界。
