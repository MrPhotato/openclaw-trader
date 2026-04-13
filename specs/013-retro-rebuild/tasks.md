# 任务分解：异步交锋式 Retro 重构

**功能分支**：`codex/013-retro-rebuild`  
**规格文档**：`/Users/chenzian/openclaw-trader/specs/013-retro-rebuild/spec.md`

## 第一波：规格与契约收口

- [ ] T001 完成 `/Users/chenzian/openclaw-trader/specs/013-retro-rebuild/spec.md`、`plan.md`、`research.md`、`data-model.md`、`quickstart.md`
- [ ] T002 完成 `/Users/chenzian/openclaw-trader/specs/013-retro-rebuild/contracts/retro-case.asset.schema.json`、`retro-brief.schema.json`、`learning-directive.asset.schema.json`

## 第二波：WO 复盘状态机

- [ ] T003 [US1] 在 `/Users/chenzian/openclaw-trader/src/openclaw_trader/modules/workflow_orchestrator/models.py` 中新增 retro cycle 状态模型
- [ ] T004 [US1] 在 `/Users/chenzian/openclaw-trader/src/openclaw_trader/modules/workflow_orchestrator/service.py` 中新增 retro 生命周期编排入口
- [ ] T005 [US1] 在 `/Users/chenzian/openclaw-trader/src/openclaw_trader/modules/workflow_orchestrator/service.py` 中把旧的 Chief retro 手动入口改成 `run_retro_prep`，并由 WO 在 briefs ready 时触发 Chief cron
- [ ] T006 [US1] 在 `/Users/chenzian/openclaw-trader/src/openclaw_trader/modules/workflow_orchestrator/` 中增加 brief 截止、degraded 收口和 Chief synthesis 触发逻辑

## 第三波：Memory Assets 新真相

- [ ] T007 [US2] 在 `/Users/chenzian/openclaw-trader/src/openclaw_trader/modules/memory_assets/models.py` 中新增 `retro_case`、`retro_brief`、`learning_directive` 资产模型
- [ ] T008 [US2] 在 `/Users/chenzian/openclaw-trader/src/openclaw_trader/modules/memory_assets/service.py` 中新增读写与按 `cycle_id` 查询接口

## 第四波：AG 收口为 pull/submit 契约层

- [ ] T009 [US3] 在 `/Users/chenzian/openclaw-trader/src/openclaw_trader/modules/agent_gateway/models.py` 中新增 `RetroBriefSubmission`
- [ ] T010 [US3] 在 `/Users/chenzian/openclaw-trader/src/openclaw_trader/modules/agent_gateway/service.py` 中新增 `submit_retro_brief(...)`
- [ ] T011 [US3] 在 `/Users/chenzian/openclaw-trader/src/openclaw_trader/app/api.py` 中新增 `POST /api/agent/submit/retro-brief`
- [ ] T012 [US3] 在 `/Users/chenzian/openclaw-trader/src/openclaw_trader/modules/agent_gateway/service.py` 中把 PM / RT / MEA 现有 pull 包扩展为可携带 `retro_case`
- [ ] T013 [US3] 在 `/Users/chenzian/openclaw-trader/src/openclaw_trader/modules/agent_gateway/service.py` 中把 Chief pack 改为读取 `retro_case + retro_briefs + facts`
- [ ] T014 [US3] 在 `/Users/chenzian/openclaw-trader/src/openclaw_trader/modules/agent_gateway/service.py` 中删除或退役 `_run_retro_turn(...)` 同步会议驱动主路径

## 第五波：Learning 收口

- [ ] T015 [US4] 在 `/Users/chenzian/openclaw-trader/src/openclaw_trader/modules/workflow_orchestrator/` 中把 Chief 裁决转换为四份 `learning_directive`
- [ ] T016 [US4] 在 `/Users/chenzian/openclaw-trader/src/openclaw_trader/modules/agent_gateway/service.py` 中让 PM / RT / MEA / Chief runtime pack 带上待处理 `learning_directive`
- [ ] T017 [US4] 在 `/Users/chenzian/openclaw-trader/src/openclaw_trader/modules/workflow_orchestrator/` 中增加 learning 文件 fingerprint 核验，不再以 `sessions_send` 回执判断完成

## 第六波：Agent 行为收口

- [ ] T018 [US5] 更新 `/Users/chenzian/openclaw-trader/skills/chief-retro-and-summary/SKILL.md` 与相关 references，把 Chief 从“主持同步会”改成“读取 briefs 做裁决”
- [ ] T019 [US5] 更新 PM / RT / MEA 的 skill 与 workspace 文档，让它们在存在 `retro_case` 时优先提交 `retro_brief`
- [ ] T020 [US5] 明确 learning 继续只走 `/self-improving-agent`，禁止 Chief 代写或同步追确认

## 第七波：验证与回归

- [ ] T021 [US6] 补 `/Users/chenzian/openclaw-trader/tests/test_v2_workflow_orchestrator.py`，覆盖 retro cycle 状态推进与 degraded 场景
- [ ] T022 [US6] 补 `/Users/chenzian/openclaw-trader/tests/test_v2_agent_gateway.py`，覆盖 `retro_brief` submit、Chief pack 聚合和 pending directives
- [ ] T023 [US6] 补 `/Users/chenzian/openclaw-trader/tests/test_v2_memory_assets.py`，覆盖 retro assets 与 learning directive 查询
- [ ] T024 [US6] 做一轮 live smoke，验证 `retro_case -> briefs -> chief_retro -> learning_directives` 链条能跑通
