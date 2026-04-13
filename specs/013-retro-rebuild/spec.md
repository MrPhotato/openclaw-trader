# 功能规格说明：异步交锋式 Retro 重构

**功能分支**：`codex/013-retro-rebuild`  
**创建日期**：2026-04-12  
**状态**：草案  
**输入描述**：将 Chief Retro 从 AG 主持的同步会议，改造成由 Workflow Orchestrator 编排的异步交锋式复盘；保留现有 runtime pack、pull/submit helper 和 `self-improving-agent` learning 机制。

## 1. 背景与目标

当前 Chief Retro 的设计目标是正确的：由 Chief 带团队分析“为什么今天没有赚到 1%”，允许 PM、RT、MEA 互相 challenge，并把争论结果沉淀成各自的 learning。

当前实现的问题不在目标，而在协议形态。现在的 retro 主要由 `agent_gateway` 驱动一场同步轮次会议，再由 Chief 在会后通过 cross-session delivery 催各 agent 记录 learning。这条链同时暴露了多种脆弱点：

- retro 编排权落在 `agent_gateway`，而不在 `workflow_orchestrator`
- 会议强依赖单次 `input_id` 贯穿整场会，容易出现 lease 过期或重复消费
- learning 成功与否过度依赖 `sessions_send` 的同步结果，而不是事实落地
- Chief 既要主持争论，又要承担分发和确认，角色负担过重

本功能的目标是：

- 把 retro 的**阶段编排权**收回 `workflow_orchestrator`
- 保留 `agent_gateway` 作为统一的 agent pull/submit 合约层
- 保留团队交锋，但把“同步会议”改成“异步 brief + Chief 裁决”
- 保留 `self-improving-agent` 作为唯一 learning 轮子
- 用 artifact 和文件事实来判断 learning 是否落地，而不是消息回执

## 2. 当前系统基线

- `workflow_orchestrator` 当前只负责触发和收口 Chief retro，不直接主持 retro 内容。
- `agent_gateway` 当前承载：
  - `pull_chief_retro_pack`
  - `run_retro_prep`
  - `_run_retro_turn`
  - `_run_retro_summary`
  - `_capture_retro_learning_targets`
  - `_validate_retro_learning_results`
- Chief 当前通过 [pull_chief_retro.py](/Users/chenzian/openclaw-trader/scripts/pull_chief_retro.py) 和 [submit_chief_retro.py](/Users/chenzian/openclaw-trader/scripts/submit_chief_retro.py) 拉取和提交 retro。
- PM / RT / MEA / Chief 的个人 learning 已统一规定必须由各自 session 内的 `/self-improving-agent` 完成，不能互相代写。
- 当前 retro learning 的技术问题不是没有轮子，而是 Chief 在错误的位置承担了 cross-session 协调责任。

## 3. 用户场景与验收

### 场景 1：WO 编排一轮异步 retro，而不是 AG 主持同步 roundtable

系统在日终复盘窗口创建一份 `retro_case`，再要求 PM / RT / MEA 分别提交自己的 retro brief。Chief 最后读取事实快照和三份 brief，输出裁决与 owner summary。

**验收标准**

1. `workflow_orchestrator` 能创建一轮带明确阶段状态的 retro cycle，并记录 `retro_case`、brief 收集状态和 Chief synthesis 触发状态。
2. `agent_gateway` 不再主持 `PM -> RT -> MEA -> Chief` 的同步轮次会议。

### 场景 2：团队可以互相 challenge，但 learning 不再靠 Chief 追回执

PM / RT / MEA 各自先提交自己的判断和对别人的 challenge。Chief 再对三份 brief 做裁决，给出各自 learning directive。后续各 agent 在自己下一次被唤醒时，通过 `/self-improving-agent` 写入自己的 learning。

**验收标准**

1. Chief 的输出包含对 PM / RT / MEA 各自的 learning directive。
2. learning 是否完成由各 agent 自己的 learning 文件或对应事实痕迹判断，不以 `sessions_send timeout` 为失败依据。

## 4. 功能需求

- **FR-001**：系统必须新增一轮 retro 的显式状态机，由 `workflow_orchestrator` 负责创建、推进和收口。
- **FR-002**：每轮 retro 必须有一份不可变的 `retro_case`
  中文：复盘题目包
  至少包含：
  - 目标收益与实际结果
  - 关键策略 revision 摘要
  - 关键执行批次摘要
  - 关键新闻/事件摘要
  - 本轮核心问题
  - 2 到 4 条 challenge prompts
- **FR-003**：PM / RT / MEA 必须各自产生一份 `retro_brief`
  中文：复盘短 memo
  每份至少包含：
  - 该角色认为今天没达到目标的主因
  - 对其他角色的 challenge
  - 对自己的承认与纠偏
  - 明日最该改的一条
- **FR-004**：`workflow_orchestrator` 必须负责 brief 的截止时间、缺失容忍和降级收口；即使缺失单个 brief，也必须能在明确标注 `degraded` 的前提下继续 Chief synthesis。
- **FR-005**：`agent_gateway` 必须保留 agent pull/submit 契约层职责，但不再承载 retro 的轮次顺序和会场状态。
- **FR-006**：PM / RT / MEA 的 retro brief 必须通过结构化正式提交通道进入系统，不能只停留在 session 文本里。
- **FR-007**：Chief synthesis 必须基于：
  - `retro_case`
  - 已提交的 `retro_brief`
  - 当前既有 facts
  产出正式 `chief_retro`
  中文：Chief 裁决型复盘
- **FR-008**：Chief 的正式 retro 输出必须包含：
  - 根因排序
  - 对 PM / RT / MEA 的裁决
  - 明日最该改的 1 到 3 条
  - 每个角色的 `learning_directive`
    中文：学习指令
- **FR-009**：learning 必须继续只由各自 agent 在各自 session 中通过 `/self-improving-agent` 完成；Chief 不得代写其他角色的 learning 文件。
- **FR-010**：系统必须用事实核验 learning 是否落地，至少支持比较 learning 文件的 baseline fingerprint 与当前 fingerprint，而不是把 `sessions_send` 返回状态当成唯一真相。
- **FR-011**：retro 周期不得跨越 `workflow_orchestrator` 的统一 `/new` 边界；系统必须保证 retro_case 创建、brief 截止和 Chief synthesis 处于同一可控窗口。
- **FR-012**：`replay_frontend` 和 owner summary 查询必须能看到本轮 retro 的：
  - retro_case
  - 各角色 brief
  - chief_retro
  - learning directive 与完成状态

## 5. 非功能要求

- **NFR-001**：新方案必须保留 team challenge，不得退化为单 Agent 总结。
- **NFR-002**：新方案必须避免同步群聊式 roundtable 对 lease、timeout 和 cross-session fan-out 的脆弱依赖。
- **NFR-003**：新方案必须复用现有轮子：runtime pack、pull/submit helper、`self-improving-agent`、`memory_assets`。
- **NFR-004**：任何 retro 阶段失败都必须明确进入 `degraded` 或 `failed`，不得长期停留在语义不清的中间态。
- **NFR-005**：`workflow_orchestrator` 只负责流程状态机，不得下沉到拼 prompt、懂各类 JSON payload 细节或代替 AG 做 schema 校验。

## 6. 关键实体

- **RetroCase（复盘题目包）**：一轮 retro 的不可变问题快照，包含目标、结果、关键事实和 challenge prompts。
- **RetroBrief（复盘短 memo）**：PM / RT / MEA 分别提交的短结构化观点产物。
- **RetroCycle（复盘周期）**：由 `workflow_orchestrator` 管理的一轮 retro 状态机，负责记录阶段、截止时间、降级状态和收口结果。
- **ChiefRetro（Chief 裁决复盘）**：Chief 基于事实和 briefs 产生的正式裁决与 owner summary。
- **LearningDirective（学习指令）**：Chief 对每个角色下发的会后学习要求，供各角色在自己的 session 中使用 `/self-improving-agent` 执行。

## 7. 假设与约束

- 第一版不引入实时群聊插件，不引入新的第三方会议协议。
- 第一版不要求 Chief 同步等待各 agent 完成 learning；learning 完成由后续事实核验。
- `self-improving-agent` 继续作为唯一 learning 轮子，不另造第二套 learning 提交协议。
- 这次改造的重点是把 retro 编排权从 AG 收回 WO，而不是重写 PM / RT / MEA 的主业务工作流。

## 8. 成功标准

- **SC-001**：一轮 retro 在没有同步 roundtable 的情况下，仍能完整回答“为什么今天没有赚到 1%”，并保留跨角色 challenge。
- **SC-002**：Chief retro 不再因为旧 lease、meeting transcript 或 cross-session delivery 脆弱性而成为主要失败点。
- **SC-003**：每轮 retro 都能留下完整且可回放的 artifact 链：`retro_case -> briefs -> chief_retro -> learning_directives -> learning 落地事实`。
- **SC-004**：`workflow_orchestrator` 成为 retro 的明确编排 owner，`agent_gateway` 保持 pull/submit 契约 owner，模块边界恢复清晰。
