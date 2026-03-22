# 功能规格说明：上下文视图与多智能体网关

> **迁移说明（2026-03-19）**：`context_builder` 已从当前主架构中移除；运行时输入编译职责已吸收进 `agent_gateway`，Agent 的阅读顺序与行为约束转入专属 skill。本文继续保留为历史横切 feature 文档。

**功能分支**：`codex/006-context-agent-gateway`  
**创建日期**：2026-03-11  
**状态**：草案  
**输入描述**：定义 4 个 Agent 的运行时输入、任务与回执契约，以及 OpenClaw 作为外部协作环境的网关边界。

## 1. 背景与目标

`001` 已经把单一 `crypto-chief` 拆解为 4 个角色，`003-005` 也已经定义了控制面、市场与风险输出、策略和执行主脊梁。`006` 的任务是把这些结构化事实编译成不同 Agent 的运行时输入，并明确多 Agent 网关与 OpenClaw 的边界。

本 feature 当前只保留为历史横切说明，记录：

- 运行时输入已迁移至 `agent_gateway`
- skill 已吸收 Agent 阅读顺序与行为 SOP
- 多智能体协作网关仍是正式提交入口

## 1.1 2026-03-12 收敛决议

经过角色职责讨论，确认 `Risk Trader` 不应被系统提前生成的候选动作束缚。

本轮已经确认的方向：

- `Risk Trader` 是高频苏醒的交易判断角色，不是被动审核器。
- 提供给 `Risk Trader` 的应是 `ExecutionContext`，而不是强建议性的 `TradeCandidate`。
- `PM` 负责策略和目标仓位，`Risk Trader` 负责在当前市场、账户和硬风控边界内决定是否执行以及如何执行。
- `Macro & Event Analyst` 继续提供事件信息源，`Crypto Chief` 负责更高层统筹、复盘与升级处理。
- 上下文构建层应尽量减少对 Agent 的提示性约束，优先提供事实、边界和必要历史。
- 第一批不让任何 Agent 进入运行主链；接口与视图保留，但工作流停在结构化上下文。

## 1.2 2026-03-14 Macro & Event Analyst 工作流决议

围绕 `Macro & Event Analyst` 的真实岗位职责，本 feature 已确认以下方向：

- `Macro & Event Analyst` 不是全量新闻中继站，而是负责筛选、语义归并、事件更新和对其他 Agent 的必要提醒。
- `Macro & Event Analyst` 的基础工作模式是“低频巡检 + 事件驱动唤醒”，常态由控制平面每 `2` 小时触发一次，新闻批次到达时即时触发。
- `Macro & Event Analyst` 可自主决定是否通过 `/gemini` 做扩搜或交叉验证；搜索指令必须以 `Web search for ...` 或 `联网搜索：...` 开头，系统不对其增加额外限频策略。
- `Macro & Event Analyst` 的记录结果必须精简到 `1-2` 句话，不输出长篇分析。
- `Macro & Event Analyst` 的正式系统提交只保留结构化事件列表，不再保留 `alert` 字段。
- `Macro & Event Analyst` 不负责普通事件的系统分发路由；正式事件统一进入 `memory_assets`，由其他模块和 Agent 读取。
- `Macro & Event Analyst` 可在 OpenClaw 中直接与其他 Agent 沟通即时提醒、追问和升级；其中，面向 `PM` 的策略影响提醒已经确认，面向 `Risk Trader` 的细化触发规则后续再单独收口。
- `Macro & Event Analyst` 的历史事件回忆后续优先复用 OpenClaw 原生记忆搜索，但该搜索层只作为 `memory_assets` 的语义检索投影，不作为新的真相源。
- `Macro & Event Analyst` 后续不得自写记忆；若启用 OpenClaw 原生语义记忆，默认要求 `autoRecall` 开启、`autoCapture` 关闭。

## 1.3 2026-03-15 Agent 协作与提交通道决议

围绕多 Agent 的真实协作方式，本 feature 进一步确认：

- Agent 间直接沟通默认允许自由发生，不必全部经由 `workflow_orchestrator` 或 MQ 中转。
- Agent 间直接沟通默认使用自然语言协作，不强制套用 JSON 回执格式。
- Agent 的正式系统提交与 Agent 间直接沟通是两条不同通道：
  - 直接沟通负责提醒、追问、澄清与协商
  - 正式提交负责产生系统内有效结果
- 只有正式提交通道才要求使用结构化契约；按角色不同，可进一步要求 JSON，例如 `Risk Trader` 的 `ExecutionDecision`。
- 直接沟通本身不形成系统真相；系统真相仍由对应模块接收正式提交后写入 `memory_assets`。

## 2. 当前系统基线

- 当前 LLM 输入散落在 `strategy/inputs.py`、`briefs.py`、`dispatch/prompts.py` 和 workspace 文件中。
- 当前外部行为主体主要还是 `crypto-chief`，而未来目标是 PM、Risk Trader、Macro & Event Analyst、Crypto Chief 四角色协作。
- 当前 OpenClaw 通过 `openclaw agent --agent ...` 和 `openclaw message send` 接入，本质上是外部协作环境中的 Agent 协作层，不是业务模块本身，也不是系统真相源。
- 本 feature 依赖 `004` 的信息源和 `005` 的交易主脊梁实体。

## 3. 用户场景与验收

### 场景 1：实现者需要稳定的 Agent 视图

实现者在接入 4 个 Agent 时，不需要再自己决定每个角色能看到哪些信息和不能看到哪些信息。

**验收标准**

1. 必须定义 PM、Risk Trader、Macro & Event Analyst、Crypto Chief 四种角色化运行时输入。
2. 必须定义每种视图显式包含和排除的信息源。

### 场景 2：系统需要稳定的多 Agent 契约

后续实现者必须能在不碰业务模块的情况下，独立实现 Agent 任务派发、回执、升级与 OpenClaw 适配。

**验收标准**

1. 必须定义 `AgentTask`、`AgentReply`、`AgentEscalation` 契约。
2. 必须定义 OpenClaw 网关边界和 session 路由规则。

## 4. 功能需求

- **FR-001**：系统必须定义四类角色化运行时输入：PM 策略输入、Risk Trader 执行输入、Macro & Event Analyst 事件输入、Crypto Chief 统筹输入。
- **FR-002**：系统必须定义 `AgentRuntimeInput` 实体，显式声明来自哪些结构化信息源。
- **FR-003**：系统必须定义 `AgentTask`、`AgentReply`、`AgentEscalation` 契约，并明确这些契约只约束进入系统收口链的正式提交与升级。
- **FR-004**：系统必须明确 OpenClaw 是外部协作环境中的 Agent 协作层；Agent 可在其中直接沟通，但不得直接写本地状态、不直接下单，正式资产提交仍须经对应模块收口。
- **FR-005**：系统必须定义升级规则和回执规则，确保下级 Agent 无法静默沉没异常。
- **FR-006**：本 feature 不定义策略算法、不定义风险边界、不定义通知投递细节。
- **FR-007**：Risk Trader 视图必须以 `ExecutionContext` 为核心，默认不包含强建议性的预生成执行动作。
- **FR-008**：第一批必须保留 4 个 Agent 的接口和文档，但主工作流不得真正调用任何 Agent。
- **FR-009**：Risk Trader 的未来正式系统提交通道必须支持 JSON 结构化输出，默认按币种 `decisions[]` 组织。
- **FR-010**：Macro & Event Analyst 的正式系统提交必须支持结构化事件列表，且每条事件摘要默认限制为 `1-2` 句话。
- **FR-011**：Macro & Event Analyst 的正式系统提交不得包含 `alert` 字段；与其他 Agent 的即时提醒和追问不通过该字段编码。
- **FR-012**：Macro & Event Analyst 不得承担普通事件分发职责；PM 与 Risk Trader 的正式事件记忆读取必须以 `memory_assets` 为准。
- **FR-013**：本 feature 必须允许 `Macro & Event Analyst` 直接向 `PM` 发送会影响策略 thesis、目标仓位、scheduled recheck 或 invalidation 的即时提醒；该提醒不等于正式策略更新。
- **FR-014**：Agent 间直接沟通默认不受 JSON 回执契约约束；只有正式提交通道才要求使用结构化契约。
- **FR-015**：本 feature 必须允许 Macro & Event Analyst 在任务内自主决定是否通过 `/gemini` 做扩搜，但搜索指令必须以 `Web search for ...` 或 `联网搜索：...` 开头，且不得将该能力设计成常驻轮询机制。
- **FR-016**：本 feature 必须允许 `Macro & Event Analyst` 通过 OpenClaw 原生记忆搜索读取其历史事件记忆，但该搜索内容必须来自 `memory_assets` 投影出的结构化记忆视图。
- **FR-017**：本 feature 必须禁止 `Macro & Event Analyst` 通过 OpenClaw 自动捕获或自行写入方式修改长期事件记忆；长期记忆写入权只属于 `memory_assets`。

## 5. 非功能要求

- **NFR-001**：上下文视图必须可版本化，便于后续增量演进。
- **NFR-002**：Agent 输入输出契约必须与实现语言和具体模型提供商无关。
- **NFR-003**：文档必须足够稳定，使后续实现者能独立重建多 Agent 协作层。
- **NFR-004**：Macro & Event Analyst 的输出必须优先呈现事件结论和风险提醒，而不是原始新闻堆叠。
- **NFR-005**：若启用 OpenClaw 原生语义记忆，检索层与真相源必须单向同步，避免双写和生命周期冲突。

## 6. 关键实体

- **AgentRuntimeInput**：供某个 Agent 消费的结构化运行时输入包。
- **AgentTask**：发给某个 Agent 的任务。
- **AgentReply**：Agent 返回的结构化回执。
- **AgentEscalation**：Agent 无法自主处理时抛出的升级事件。

## 7. 假设与约束

- 4 Agent 是目标态；本 feature 只写契约，不要求当前运行态已切到 4 Agent。
- 第一批允许在代码中保留确定性适配器或占位实现，但不得把 Agent 调用挂回主工作流。
- OpenClaw 继续作为外部协作环境保留，不内嵌到核心业务模块。
- workspace 文本规则未来仍存在，但要降级为契约和视图的消费者，而不是唯一真相源。

## 8. 成功标准

- **SC-001**：后续实现者可以基于本 feature 独立搭出多 Agent 网关，不需要重回当前 prompt 拼接逻辑。
- **SC-002**：每个 Agent 的职责、输入、输出、升级边界都在文档中明确，无需二次拍板。
- **SC-003**：OpenClaw 被清晰定义为 Agent 协作层而非业务真相层，不再与本地模块真相源混在一起。
