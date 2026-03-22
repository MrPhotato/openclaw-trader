# 模块清单与现有代码映射

> **迁移说明（2026-03-15）**：模块级主真相层已迁移到 `specs/modules/README.md`。本文件继续保留为旧蓝图到新实现的映射说明，不再单独定义最高模块边界。

本文件把“未来 11 模块”映射到“当前代码与文档”，用于后续重构收口。

| 模块 | 未来职责 | 当前主要代码 / 文档落点 | 当前真相源 | 未来输入 / 输出 | 当前缺口 |
| --- | --- | --- | --- | --- | --- |
| 交易网关 | 统一负责交易所接入边界，内部拆分为 `market_data` 与 `execution` 两个子域，分别处理事实读取与下单执行 | `coinbase.py`、`perps/coinbase_intx.py`、`engine.py`、`cli.py` / `service.py` 的下单接口、`market_intelligence/features.py` | 交易所 API、账户、订单结果、运行态快照 | 输入：外部交易所源；输出：标准化市场/账户事实、执行结果、价格形态上下文、执行历史与失败统计 | 当前新代码已收口到 `Trade Gateway`，但仍需补齐多尺度价格序列、形态摘要、关键价位、突破/回踩、波动扩张/收缩、最近订单/成交历史以及可选的订单簿深度信息 |
| 新闻事件 | 轮询固定新闻源、做轻去重与标准化、生成新闻批次并发出 `NEWS_BATCH_READY` 事件，作为 `Macro & Event Analyst` 的原始信息底盘 | `news/service.py`、`market_intelligence/events.py`、`market_intelligence/event_policy.py`、`perps/runtime/news.py`、`docs/market-intelligence.md` | 固定新闻源、新闻批次文件、事件队列 | 输入：原始新闻；输出：标准化新闻批次、基础分类、批次就绪事件 | 当前语义归并、事件生命周期和长期记忆不应由本模块直接承担 |
| 量化判断 | 训练与推理 `1h/4h/12h`、regime、trade quality、多时域组合判断 | `market_intelligence/pipeline.py`、`market_intelligence/context.py`、`market_intelligence/features.py`、`docs/market-intelligence.md` | `~/.openclaw-trader/models/`、模型 meta、calibration 报告 | 输入：标准化市场事实；输出：多时域判断与诊断 | 当前部分 policy 逻辑仍混在量化层 |
| 风控与执行守卫 | 产出硬风控边界、风险上限、事件限制、组合风险和不确定性约束 | `market_intelligence/policy.py`、`risk.py`、`perps/runtime/calculations.py`、`strategy-and-risk.md` | runtime config、风险阈值、组合快照 | 输入：量化判断、事件、账户；输出：硬边界 | 当前与 runtime 执行翻译耦合较深 |
| 策略与组合意图 | 定义目标仓位、版本、recheck、thesis / invalidation | `strategy/__init__.py`、`strategy/rewrite.py`、`strategy/history.py`、`docs/strategy-and-risk.md` | `strategy-day.json/md`、change log、journal | 输入：风控边界、组合状态；输出：策略意图 | 当前与上下文构建、报表输出混在一起 |
| 状态机与编排器 | 收口工作流状态、统一触发入口、推进策略/执行链路，并负责 Agent 的基础计时器、生命周期管理与 OpenClaw 托管式后续调度 | `dispatch/__init__.py`、`dispatch/planning.py`、`dispatch/state_flow.py`、`dispatch/strategy_flow.py`、`dispatch/execution.py` | dispatch brief、state marks、运行时状态、事件队列 | 输入：策略意图、风控边界、执行事实、外部命令、新闻批次事件、Agent 结果事件；输出：流程命令、状态记录、预约任务 | 当前状态机未完全显式化，编排过重，且尚缺对 `Macro & Event Analyst` 的正式触发/重置规则 |
| 上下文构建 | 为不同任务 / Agent 构建统一上下文视图 | `strategy/inputs.py`、`briefs.py`、`dispatch/prompts.py`、`strategy/build_strategy_memory_perps` | strategy input、brief、报表 | 输入：多模块结构化事实；输出：上下文视图 | 当前散落在策略、brief、prompt 多处 |
| 多智能体协作网关 | 管理 OpenClaw、4 个 Agent、session、回执、升级；其中 `Macro & Event Analyst` 负责筛选、语义归并、精简事件摘要与必要提醒 | `dispatch/OpenClawAgentRunner`、`dispatch/prompts.py`、`docs/dispatch-and-sessions.md` | agent transcript、reply routing 配置、任务结果事件 | 输入：AgentTask；输出：Agent 回执 / 升级 | 当前主要围绕单一 `crypto-chief` 展开，`Macro & Event Analyst` 的正式工作流尚未实现 |
| 状态与记忆管理 | 统一保存状态、事件索引、策略历史、记忆提炼、报表元数据；其中 `Macro & Event Analyst` 事件记忆为唯一真相源，不保留独立私有记忆文件，并向 OpenClaw 原生记忆搜索提供只读投影 | `state.py`、`briefs.py`、`strategy/history.py`、runtime `reports/` | SQLite、reports、jsonl、journal、事件队列 | 输入：事件与结果；输出：查询视图、记忆视图、语义检索投影 | 当前 state、report、memory 分散在多个载体中，且 `Macro` 事件记忆尚未正式结构化 |
| 通知服务 | 确定性文案、发送路由、去重、转发和交付回执 | `dispatch/notifications.py`、reply channel 配置、owner 路由 | notification marks、OpenClaw message send | 输入：确定性消息命令；输出：发送结果 | 当前部分通知仍通过 LLM 文案生成 |
| 回放与前端 | 实时监控、历史回放、参数调节、模块协作可视化 | 当前无独立模块；依赖 `briefs.py`、`state.py`、logs、reports | brief、journal、SQLite、logs | 输入：结构化事件、查询接口；输出：UI、回放、调参界面 | 当前仍缺独立实现与协议约束 |

## 进一步拆分提示

### 需要优先拆开的当前文件

- `dispatch/__init__.py`
- `perps/runtime/__init__.py`
- `strategy/__init__.py`
- `briefs.py`

### 最容易先收口成模块边界的目录

- `coinbase.py`
- `engine.py`
- `market_intelligence/`
- `state.py`

### 当前完全缺失、需要新建的未来边界

- 统一外部主动触发 API
- 结构化事件协议与事件写入器
- RabbitMQ 发布 / 订阅层
- 多 Agent 网关
- 回放与前端服务
