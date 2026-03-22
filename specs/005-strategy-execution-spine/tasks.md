# 任务分解：策略与执行主脊梁

**功能分支**：`codex/005-strategy-execution-spine`  
**规格文档**：`specs/005-strategy-execution-spine/spec.md`

## 第一波：主脊梁范围

- [x] T001 明确策略意图、执行上下文、执行决策、执行计划、执行结果之间的边界，写入 `specs/005-strategy-execution-spine/spec.md`
- [x] T002 固化动作集合与执行决策边界，写入 `specs/005-strategy-execution-spine/spec.md`

## 第二波：数据模型与契约

- [x] T003 定义五个核心实体，写入 `specs/005-strategy-execution-spine/data-model.md`
- [x] T004 [P] 编写策略意图 schema，写入 `specs/005-strategy-execution-spine/contracts/strategy-intent.schema.json`
- [x] T005 [P] 编写执行上下文 schema，写入 `specs/005-strategy-execution-spine/contracts/execution-context.schema.json`
- [x] T006 [P] 编写执行决策 schema，写入 `specs/005-strategy-execution-spine/contracts/execution-decision.schema.json`
- [x] T007 [P] 编写执行计划 schema，写入 `specs/005-strategy-execution-spine/contracts/execution-plan.schema.json`
- [x] T008 编写 contracts 索引和使用说明，写入 `specs/005-strategy-execution-spine/contracts/README.md`

## 第三波：质量与衔接

- [x] T009 编写实施计划，写入 `specs/005-strategy-execution-spine/plan.md`
- [x] T010 编写 quickstart，写入 `specs/005-strategy-execution-spine/quickstart.md`
- [x] T011 编写一致性分析报告，写入 `specs/005-strategy-execution-spine/analysis.md`
- [x] T012 完成 requirements checklist，写入 `specs/005-strategy-execution-spine/checklists/requirements.md`

## 第四波：收敛改造

- [x] T013 收缩 `strategy_intent`，使其仅负责承接 PM 输出并标准化为目标仓位状态
- [x] T014 用 `ExecutionContext` 取代旧候选单作为主执行输入对象
- [x] T015 更新数据模型与 contracts，移除对强建议性候选动作的依赖
- [x] T016 调整 `ExecutionPlan` 生成链，使其只消费 `Risk Trader` 的结构化决策结果
- [ ] T017 第二批再将 PM 的真实输出接回 `strategy_intent`
- [ ] T018 第二批再将 `ExecutionDecision` 真正接入执行主链
