# 任务分解：上下文视图与多智能体网关

**功能分支**：`codex/006-context-agent-gateway`  
**规格文档**：`specs/006-context-agent-gateway/spec.md`

## 第一波：视图与角色边界

- [x] T001 定义四个 Agent 角色的职责和不负责事项，写入 `specs/006-context-agent-gateway/spec.md`
- [x] T002 定义四个角色化运行时输入的包含源和排除源，写入 `specs/006-context-agent-gateway/spec.md`

## 第二波：数据模型与契约

- [x] T003 定义 `AgentRuntimeInput`、`AgentTask`、`AgentReply`、`AgentEscalation`，写入 `specs/006-context-agent-gateway/data-model.md`
- [x] T005 [P] 编写 AgentTask schema，写入 `specs/006-context-agent-gateway/contracts/agent-task.schema.json`
- [x] T006 [P] 编写 AgentReply schema，写入 `specs/006-context-agent-gateway/contracts/agent-reply.schema.json`
- [x] T007 编写 contracts 索引和 OpenClaw 网关边界说明，写入 `specs/006-context-agent-gateway/contracts/README.md`

## 第三波：质量与衔接

- [x] T008 编写实施计划，写入 `specs/006-context-agent-gateway/plan.md`
- [x] T009 编写 quickstart，写入 `specs/006-context-agent-gateway/quickstart.md`
- [x] T010 编写一致性分析报告，写入 `specs/006-context-agent-gateway/analysis.md`
- [x] T011 完成 requirements checklist，写入 `specs/006-context-agent-gateway/checklists/requirements.md`

## 第四波：收敛改造

- [x] T012 调整 Risk Trader 视图，使其以 `ExecutionContext` 为核心而非预生成候选动作
- [x] T013 收缩上下文中的提示性约束，优先提供事实、硬边界和必要历史
- [x] T014 明确 PM 与 Risk Trader 的职责断点：PM 产出目标仓位，Risk Trader 产出执行决策
- [x] T015 补充 Crypto Chief 与 Macro & Event Analyst 在新分工下的升级与汇报约束
- [ ] T016 第二批再将 PM / Risk Trader / Macro / Chief 真正接入主工作流

## 第五波：MEA 事件工作流收敛

- [x] T017 固化 Macro & Event Analyst 的“低频巡检 + 事件驱动唤醒”工作模式
- [x] T018 固化 Macro & Event Analyst 的精简输出要求：每条事件 `1-2` 句话，移除 `alert` 字段，正式提交只保留结构化事件列表
- [x] T019 固化 PM 以 `memory_assets` 为正式事件记忆来源，同时允许 `MEA` 直接向 `PM` 发送策略影响提醒
- [x] T020 固化 Agent 双通道：Agent 间直接沟通默认自由，只有正式提交通道才要求结构化，JSON 仅约束角色特定的正式提交契约
- [ ] T021 第二批接入 OpenClaw 原生记忆搜索，使 `Macro & Event Analyst` 可通过语义召回读取 `memory_assets` 投影出的事件记忆
- [ ] T022 第二批明确 `Macro & Event Analyst` 的记忆读取契约，要求 `memory_view_id` 和 `memory_recall_mode` 与 `memory_assets` 投影保持一致
