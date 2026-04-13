# Quickstart：异步交锋式 Retro

## 目标

验证新版 retro 是否满足：

- WO 编排
- AG 只做 pull/submit 契约
- PM / RT / MEA 各自提交 brief
- Chief 只做 synthesis
- learning 通过 `/self-improving-agent` 自行完成

## 推荐验证顺序

1. 创建一轮 `retro_case`
   - 确认 `workflow_orchestrator` 写入 `retro_cycle_state`
   - 确认 `memory_assets` 有 `retro_case`

2. 分别触发 PM / RT / MEA brief
   - 各角色从自己现有 pull 入口拿到 `retro_case`
   - 通过 `submit/retro-brief` 提交
   - `memory_assets` 中出现对应的 `retro_brief`

3. Chief synthesis
   - `pull_chief_retro.py` 读到：
     - `retro_case`
     - `retro_briefs`
     - 当前 cycle 状态
   - `submit_chief_retro.py` 成功提交 `chief_retro`

4. learning directives
   - `memory_assets` 中出现四份 `learning_directive`
   - 各角色下一次 wakeup 时，在自己的 runtime pack 中读到待处理 directive

5. learning 落地核验
   - 每个角色通过 `/self-improving-agent` 更新自己的 canonical learning 文件
   - 系统根据 baseline fingerprint 与当前 fingerprint 标记 directive 为 `completed`

## 关键验收点

- 没有同步 roundtable transcript 作为正式主链
- 没有 Chief 会后强依赖 `sessions_send` fan-out
- 即使缺失一个 brief，也能以 `degraded` 收口
- retro cycle 不跨越 `/new` 边界
