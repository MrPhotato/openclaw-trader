# 任务分解：状态、记忆与交付层

**功能分支**：`codex/007-state-memory-delivery`  
**规格文档**：`specs/007-state-memory-delivery/spec.md`

## 第一波：交付边界

- [x] T001 固化状态、记忆、通知、回放/前端四者边界，写入 `specs/007-state-memory-delivery/spec.md`
- [x] T002 固化前端和通知只能消费结构化事件/读模型的原则，写入 `specs/007-state-memory-delivery/spec.md`

## 第二波：数据模型与契约

- [x] T003 定义状态快照、记忆视图、通知命令/结果、回放查询视图，写入 `specs/007-state-memory-delivery/data-model.md`
- [x] T004 [P] 编写状态快照 schema，写入 `specs/007-state-memory-delivery/contracts/state-snapshot.schema.json`
- [x] T005 [P] 编写通知命令 schema，写入 `specs/007-state-memory-delivery/contracts/notification-command.schema.json`
- [x] T006 [P] 编写回放查询 OpenAPI，写入 `specs/007-state-memory-delivery/contracts/replay-query.openapi.yaml`
- [x] T007 编写 contracts 索引和消费说明，写入 `specs/007-state-memory-delivery/contracts/README.md`

## 第三波：质量与交付闭环

- [x] T008 编写实施计划，写入 `specs/007-state-memory-delivery/plan.md`
- [x] T009 编写 quickstart，写入 `specs/007-state-memory-delivery/quickstart.md`
- [x] T010 编写一致性分析报告，写入 `specs/007-state-memory-delivery/analysis.md`
- [x] T011 完成 requirements checklist，写入 `specs/007-state-memory-delivery/checklists/requirements.md`

## 第四波：Macro 事件记忆

- [x] T012 固化 `Macro & Event Analyst` 事件记忆的唯一真相源为 `memory_assets`
- [x] T013 定义 `MacroEventRecord` 与 `MacroDailyMemory` 的最简记忆模型
- [x] T014 固化“只存结构化事件，不存原始新闻”的边界
- [x] T015 固化除 `learning` 外所有真实资产统一由 `memory_assets` 书写和管理
- [x] T016 固化 Agent 间直接沟通不直接形成系统真相，正式决定必须经模块接收后写入 `memory_assets`
- [ ] T017 第二批定义 `memory_assets -> OpenClaw memory` 的只读记忆投影模型，避免双写
- [ ] T018 第二批接入 OpenClaw 原生语义检索，明确 `autoRecall` 开启、`autoCapture` 关闭
