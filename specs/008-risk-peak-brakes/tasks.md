# 任务分解：风控峰值刹车与双触发闭环

**功能分支**：`codex/008-risk-peak-brakes`  
**规格文档**：`specs/008-risk-peak-brakes/spec.md`

## 第一波：规格与配置

- [ ] T001 为 feature speckit 补齐 spec / plan / data-model / quickstart / research
- [ ] T002 在配置模型与运行配置中加入组合高点回撤阈值与风控刹车监控器开关

## 第二波：风控状态机

- [ ] T003 在 `policy_risk` 中新增 `PortfolioRiskState`
- [ ] T004 将单仓回撤改成 trailing peak/trough 口径
- [ ] T005 在 `authorize_execution()` 中加入 `reduce_only / flat_only` 动作矩阵

## 第三波：自动风控与双触发

- [ ] T006 新增 `workflow_orchestrator/risk_brake.py`，实现扫描、上升沿识别、状态持久化与幂等控制
- [ ] T007 实现系统风控单并复用现有执行链落账
- [ ] T008 在 `reduce/exit` 后并发触发 RT 与 PM，并让 RT 首轮绕过普通 cooldown
- [ ] T009 将风控锁释放条件收口为“检测到新的 PM strategy revision”

## 第四波：上下文与验证

- [ ] T010 在 PM / RT runtime pack 中加入 `latest_risk_brake_event`
- [ ] T011 补 `policy_risk / workflow_orchestrator / agent_gateway` 回归测试
- [ ] T012 运行单测、build 与健康检查，确认运行态稳定

