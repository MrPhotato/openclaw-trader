# 模块规格说明：Agent Gateway

**状态**：主真相层草案  
**对应实现**：`src/openclaw_trader/modules/agent_gateway/`  
**来源承接**：`001`、`006`

## 1. 背景与目标

`agent_gateway` 把 OpenClaw 定位成外部协作环境中的 Agent 协作层。它负责 agent-facing runtime bridge、正式回执、三类正式提交模板和准入校验，但不把 Agent 间直接沟通误当作系统真相。

## 2. 职责

- 管理 Agent 的运行时拉取桥、正式回执和升级契约
- 维护 `news`、`strategy`、`execution` 三类正式提交模板
- 对正式提交执行共享 schema 准入校验并发布到消息总线
- 在运行时按 Agent 角色编译单次 runtime pack
- 发放 `input_id + trace_id + expires_at` 单次租约
- 校验 formal submit 带回的 `input_id`
- 维护单 session 运行约束、provider 适配和运行时外壳
- 驱动内部复盘会的轮次、speaker 顺序和临时 transcript
- 明确“直接沟通”与“正式提交”的边界

## 3. 拥有资产

- `AgentTask`
- `AgentReply`
- `AgentEscalation`
- `AgentRuntimeInput`
- `AgentRuntimeLease`
- `FormalSubmissionTemplate`
- `ValidatedSubmissionEnvelope`
- `RetroMeetingTurn`
- `RetroMeetingResult`

## 4. 输入

- Agent 主动发起的 runtime pack pull
- 各业务模块提供的 deterministic read bridge
- `workflow_orchestrator` 提供的 trigger context、recheck 状态和生命周期信息
- Agent 运行时产生的正式提交和升级
- 项目内共享的提交 schema、prompt 片段和 examples

## 5. 输出

- 通过 schema 校验的 `news` / `strategy` / `execution` 正式提交
- 按角色编译的单次 runtime pack
- 与 runtime pack 对应的 lease、expiry 和 consumed 记录
- 升级事件
- 运行时状态和 provider 结果引用
- 内部复盘会的临时 transcript 和 meeting result

## 6. 直接协作边界

- 与 OpenClaw 作为协作环境对接
- 向 Agent 暴露本地 HTTP runtime bridge
- 向 `memory_assets`、`workflow_orchestrator`、`policy_risk`、执行域等消费者分发正式提交

## 7. 不负责什么

- 不直接写本地真相状态
- 不直接下单
- 不把 transcript 当作最终系统资产
- 不负责长期记忆管理
- 不承担业务模块的语义归并、版本化和资产持久化
- 不让 Agent 直接碰 MQ 或逐模块拉数据

## 8. 当前已定

- Agent 间直接沟通默认允许
- 只有正式提交通道受结构化契约约束
- 角色特定 JSON 约束只作用于正式提交，不作用于平时沟通
- schema 独立为 JSON 文件，同时作为 prompt 拼接输入的一部分
- 下游模块不重复做 schema 准入校验，但继续负责各自消费语义
- `strategy` 与 `news` 的系统字段由下游真相层补齐；Agent 只提交业务判断字段
- 每个 Agent 固定维护一个工作 session，不为日常任务频繁新开 session
- routing 采用静态规则，不按提交内容做智能猜测
- `execution` 类型正式提交先进入 `policy_risk`，再由其决定是否继续分发到 `Trade Gateway.execution`
- 若 schema 校验失败，AG 必须把当前 `schema_ref`、`prompt_ref` 与校验错误返回给原 Agent，并要求其重新生成纯 JSON
- OpenClaw `cron` 直接唤醒 `PM`、`RT`、`MEA`、`Chief`
- agent 醒来后第一步是向 `agent_gateway` 拉取一次 role-specific runtime pack，而不是等待 `workflow_orchestrator` 推送 payload
- role-specific runtime pack 通过本地 HTTP 暴露，最小 pull 接口固定为：
  - `POST /api/agent/pull/pm`
  - `POST /api/agent/pull/rt`
  - `POST /api/agent/pull/mea`
  - `POST /api/agent/pull/chief-retro`
- runtime pack pull 返回：
  - `input_id`
  - `trace_id`
  - `trigger_type`
  - `expires_at_utc`
  - `payload`
- formal submit 通过本地 HTTP 暴露，最小接口固定为：
  - `POST /api/agent/submit/strategy`
  - `POST /api/agent/submit/execution`
  - `POST /api/agent/submit/news`
  - `POST /api/agent/submit/retro`
- 每次 formal submit 都必须带回有效 `input_id`
- `input_id` 是最小租约与幂等单位；不引入额外 `claim/ack` 任务平台
- `agent_gateway` 作为 agent-facing bridge owner，负责向各业务模块拉取 deterministic facts 并编成角色包
- `Chief retro` 由 AG 驱动一场内部结构化会议，不依赖第三方群聊软件
- 会议固定最多 `2` 轮，每轮 speaker 顺序固定为 `PM -> RT -> MEA -> Chief`
- 每个 Agent 第一次发言时收到一次性的 compact retro pack、当前 transcript、当前轮次和本轮发言要求；第二次发言时只收到新发言 delta 和薄会议状态
- 会议 transcript 只作为临时运行态保留，不写入 `memory_assets`
- 会后 learning 指令由 `Crypto Chief` 通过各自 session 发出，但 AG 不等待 learning 文件结果，也不在 retro 流程内执行 session reset
- `POST /api/agent/submit/retro` 是正式 retro 结果提交，不重新驱动会议；最小必须字段为 `input_id + owner_summary`
- retro 正式提交成功后，AG 必须记录 `chief.retro.completed` 事件并持久化 `chief_retro` 资产

## 9. 待后续讨论

- 直接沟通的观测与审计粒度
