# 数据模型：异步交锋式 Retro 重构

## 1. RetroCycleState

中文：复盘周期状态

用途：
- 由 `workflow_orchestrator` 持有一轮 retro 的阶段状态机

字段：
- `cycle_id`
- `trade_day_utc`
- `state`
  - `case_created`
  - `brief_collection`
  - `chief_pending`
  - `completed`
  - `degraded`
  - `failed`
- `started_at_utc`
- `brief_deadline_utc`
- `chief_deadline_utc`
- `degraded_reason`
- `retro_case_id`
- `chief_retro_id`

## 2. RetroCase

中文：复盘题目包

用途：
- 一轮 retro 的不可变问题快照

字段：
- `retro_case_id`
- `cycle_id`
- `trade_day_utc`
- `goal_return_pct`
- `actual_return_pct`
- `core_question`
- `challenge_prompts[]`
- `strategy_refs[]`
- `execution_refs[]`
- `event_refs[]`
- `market_summary`
- `risk_summary`

## 3. RetroBrief

中文：复盘短 memo

用途：
- PM / RT / MEA 各自提交的结构化观点

字段：
- `retro_brief_id`
- `cycle_id`
- `agent_role`
  - `pm`
  - `risk_trader`
  - `macro_event_analyst`
- `root_cause_view`
- `peer_challenges[]`
- `self_critique`
- `tomorrow_change`
- `submitted_at_utc`

## 4. ChiefRetro

中文：Chief 裁决复盘

说明：
- 继续复用现有 `chief_retro` 正式资产
- 但其输入改为 `retro_case + retro_brief[] + facts`

新增/强化字段：
- `cycle_id`
- `root_cause_ranking[]`
- `role_judgements[]`
- `learning_directives[]`

## 5. LearningDirective

中文：学习指令

用途：
- Chief 对每个角色下发的会后学习要求
- 作为正式资产保存，供各角色下一次 wakeup 时读取

字段：
- `directive_id`
- `cycle_id`
- `target_role`
- `directive_text`
- `learning_path`
- `baseline_fingerprint`
- `issued_at_utc`
- `completed_at_utc`
- `completion_state`
  - `pending`
  - `completed`
  - `stale`

## 6. 关系

- 一个 `RetroCycleState` 对应一份 `RetroCase`
- 一个 `RetroCycleState` 对应最多三份 `RetroBrief`
- 一个 `RetroCycleState` 对应一份 `ChiefRetro`
- 一个 `ChiefRetro` 对应四份 `LearningDirective`
  - `pm`
  - `risk_trader`
  - `macro_event_analyst`
  - `crypto_chief`
