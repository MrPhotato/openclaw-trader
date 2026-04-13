# 实施计划：异步交锋式 Retro 重构

**功能分支**：`codex/013-retro-rebuild`  
**规格文档**：`/Users/chenzian/openclaw-trader/specs/013-retro-rebuild/spec.md`  
**计划日期**：2026-04-12

## 1. 执行摘要

本次改造不推翻 retro 的目标，只替换协议形态。

核心动作只有三条：

- 把 retro 的阶段状态机和编排权从 `agent_gateway` 收回 `workflow_orchestrator`
- 把同步 roundtable 改成 `retro_case -> PM/RT/MEA briefs -> Chief synthesis`
- 保留 `self-improving-agent` 作为唯一 learning 轮子，并把 learning 完成判断改成文件/事实核验

## 2. 技术背景（Technical Context）

- **现有系统事实**：
  - `workflow_orchestrator` 当前只触发 Chief retro 流程
  - `agent_gateway` 当前承载会议轮次、speaker 顺序、owner summary 和 learning target 校验
  - Chief 已有 helper：
    - `/Users/chenzian/openclaw-trader/scripts/pull_chief_retro.py`
    - `/Users/chenzian/openclaw-trader/scripts/submit_chief_retro.py`
  - learning 标准轮子已统一为 `/self-improving-agent`
- **目标边界**：
  - 不重构 PM / RT / MEA 主业务协议
  - 不引入群聊插件或第三方会议层
  - 不新增第二套 learning 提交流程
- **主要依赖**：
  - `workflow_orchestrator`
  - `agent_gateway`
  - `memory_assets`
  - `replay_frontend`
  - Chief / PM / RT / MEA 的 skill 与 workspace 提示
- **未知项 / 待确认项**：
  - 第一版不要求立即实现 UI，只要求 replay/query 能看清 retro artifact 链

## 3. 宪法检查（Constitution Check）

- retro 的状态推进必须落在显式状态机中，不能继续依赖“看 transcript 猜会议进度”。
- retro 相关事实必须进入 `memory_assets`，而不是只停留在 session 文本。
- `workflow_orchestrator` 只收回编排权，不下沉到 AG 的 schema 校验和 runtime pack 细节。

## 4. 第 0 阶段：研究与现状归档

- 确认当前主问题不是没有 learning 轮子，而是学习分发和会议协议脆弱。
- 归档当前 AG 中与 retro 相关的 6 个核心函数，作为迁移源：
  - `run_retro_prep`
  - `_run_retro_turn`
  - `_run_retro_summary`
  - `_capture_retro_learning_targets`
  - `_validate_retro_learning_results`
  - `pull_chief_retro_pack`
- 归档现有可复用轮子：
  - runtime pack
  - pull/submit helper
  - `/self-improving-agent`
  - learning 文件 fingerprint 校验

## 5. 第 1 阶段：设计与契约

- 在 `memory_assets` 中新增：
  - `retro_case`
  - `retro_brief`
  - `learning_directive`
  - `retro_cycle_state`
- 在 `workflow_orchestrator` 中新增 retro 状态机，阶段至少包括：
  - `case_created`
  - `brief_collection`
  - `chief_pending`
  - `completed`
  - `degraded`
  - `failed`
- 在 `agent_gateway` 中新增：
  - `retro_brief` 正式提交 schema
  - role-aware retro pack 视图
  - Chief synthesis pack 视图
- PM / RT / MEA 继续使用各自既有 pull 入口，但当存在待处理 retro_case 时，pack 中必须附带：
  - `retro_case`
  - `retro_cycle_state`
  - 该角色已提交 brief 的状态
- Chief 继续使用 `pull_chief_retro_pack` 和 `submit/retro`，但输入由“会议 transcript”改为“retro_case + briefs + facts”
- learning directive 不再依赖 Chief 会后 `sessions_send` 扇出；改为作为正式 asset 下发，并在各 agent 下一次 wakeup 时进入其 runtime pack

## 6. 第 2 阶段：任务分解与迁移路径

- 先补文档与 contract，明确 WO / AG 边界和 retro artifact 链
- 再实现 `memory_assets` 新资产
- 再实现 WO retro 状态机和 brief 收集/降级逻辑
- 再把 AG 从“主持会议”收口到“提供 pack + validate submit”
- 最后改 Chief / PM / RT / MEA skill，让 learning 彻底回归 `self-improving-agent`

## 7. 产物清单

- `research.md`
- `data-model.md`
- `contracts/`
- `quickstart.md`
- `tasks.md`
