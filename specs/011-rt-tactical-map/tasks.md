# 任务分解：RT 当班战术地图

**功能分支**：`codex/011-rt-tactical-map`  
**规格文档**：`specs/011-rt-tactical-map/spec.md`

## 第一波：规格与契约收口

- [X] T001 完成 `specs/011-rt-tactical-map/spec.md`、`plan.md`、`research.md`、`data-model.md`、`quickstart.md`
- [X] T002 为 `standing_tactical_map` 和 `trigger_delta` 补最小 contract，锁定字段和 ownership 边界

## 第二波：主真相层与运行包接入

- [X] T003 [US1] 在 `src/openclaw_trader/modules/memory_assets/models.py` 中增加 RT 战术地图模型
- [X] T004 [US1] 在 `src/openclaw_trader/modules/memory_assets/service.py` 中增加 RT 战术地图读写入口
- [X] T005 [US1] 在 `src/openclaw_trader/modules/agent_gateway/service.py` 中为 `pull/rt` 增加 `standing_tactical_map`
- [X] T006 [US1] 在 `src/openclaw_trader/modules/agent_gateway/service.py` 中构建 `trigger_delta`

## 第三波：RT 工作流收口

- [X] T007 [US2] 更新 `skills/risk-trader-decision/SKILL.md`，把默认工作流改为“delta -> map -> lock -> drill-down”
- [X] T008 [US2] 更新 `skills/risk-trader-decision/references/runtime-inputs.md` 和 `three-stage-funnel.md`
- [X] T009 [US2] 更新 `/Users/chenzian/.openclaw/workspace-risk-trader/AGENTS.md`，让运行态提示链采用战术地图工作流
- [X] T010 [US2] 为 RT 的提交链增加地图刷新时机与刷新原因约定

## 第四波：验证与回归

- [X] T011 [US3] 补 `tests/test_v2_agent_gateway.py`，覆盖 `standing_tactical_map` 和 `trigger_delta`
- [X] T012 [US3] 补 `tests/test_v2_workflow_orchestrator.py` 或相关测试，验证地图与现有 trigger/risk brake 共存
- [X] T013 [US3] 运行关键回归并做一次真实 `pull/rt` smoke，确认运行态已能读到地图和增量

## 第五波：收口与发布准备

- [X] T014 清理 spec 里的残留歧义，确保 `011` 可直接进入实现
- [X] T015 整理 `011` 分支提交，避免把无关 worktree 噪音带进实现阶段
