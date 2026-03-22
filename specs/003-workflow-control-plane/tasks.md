# 任务分解：工作流控制平面

**功能分支**：`codex/003-workflow-control-plane`  
**规格文档**：`specs/003-workflow-control-plane/spec.md`

## 第一波：状态机与命令规格

- [x] T001 定义工作流主状态、降级状态和终止状态，写入 `specs/003-workflow-control-plane/spec.md`
- [x] T002 定义统一主动命令集合和幂等要求，写入 `specs/003-workflow-control-plane/spec.md`

## 第二波：数据模型与契约

- [x] T003 定义命令、回执、状态记录和迁移规则实体，写入 `specs/003-workflow-control-plane/data-model.md`
- [x] T004 [P] 编写控制 API OpenAPI，写入 `specs/003-workflow-control-plane/contracts/control-api.openapi.yaml`
- [x] T005 [P] 编写工作流状态 schema，写入 `specs/003-workflow-control-plane/contracts/workflow-state.schema.json`
- [x] T006 编写控制平面契约索引，写入 `specs/003-workflow-control-plane/contracts/README.md`

## 第三波：质量与后续依赖

- [x] T007 编写控制平面实施计划，写入 `specs/003-workflow-control-plane/plan.md`
- [x] T008 编写 quickstart 与旧入口迁移说明，写入 `specs/003-workflow-control-plane/quickstart.md`
- [x] T009 编写一致性分析报告，写入 `specs/003-workflow-control-plane/analysis.md`
- [x] T010 完成 requirements checklist，写入 `specs/003-workflow-control-plane/checklists/requirements.md`

## 第四波：MEA 触发与下游收敛

- [x] T011 固化 `NEWS_BATCH_READY -> Macro & Event Analyst` 的事件驱动唤醒与 `2` 小时倒计时重置规则
- [x] T012 移除 `MEA alert -> workflow_orchestrator -> 其他 Agent` 的旧假设，固化 `workflow_orchestrator` 不订阅 `MEA` 结果、只负责客观唤醒与生命周期管理
- [x] T013 固化未来 `high` 级事件的 OpenClaw 托管式跟踪任务挂载规则（`13` 任务 / `12` 任务），但不提前把正式提交流程绑定给 `workflow_orchestrator`
