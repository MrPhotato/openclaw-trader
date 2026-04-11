# 任务分解：事件协议与进程内总线骨架

**功能分支**：`codex/002-event-envelope-bus`  
**规格文档**：`specs/002-event-envelope-bus/spec.md`

## 第一波：规格与基础约束

- [x] T001 明确 `EventEnvelope` 顶层字段、命名规则和版本策略，写入 `specs/002-event-envelope-bus/spec.md`
- [x] T002 明确进程内事件总线的事件类型与交付最小规则，写入 `specs/002-event-envelope-bus/contracts/event-routing.md`

## 第二波：设计与契约

- [x] T003 定义事件、路由、参数治理实体，写入 `specs/002-event-envelope-bus/data-model.md`
- [x] T004 [P] 编写事件信封 schema，写入 `specs/002-event-envelope-bus/contracts/event-envelope.schema.json`
- [x] T005 [P] 编写参数变更 schema，写入 `specs/002-event-envelope-bus/contracts/parameter-change.schema.json`
- [x] T006 编写 contracts 索引和使用说明，写入 `specs/002-event-envelope-bus/contracts/README.md` 与 `specs/002-event-envelope-bus/quickstart.md`

## 第三波：质量与后续依赖

- [x] T007 编写面向后续 `003-007` 的实施计划，写入 `specs/002-event-envelope-bus/plan.md`
- [x] T008 编写一致性分析报告，写入 `specs/002-event-envelope-bus/analysis.md`
- [x] T009 完成 requirements checklist，写入 `specs/002-event-envelope-bus/checklists/requirements.md`
