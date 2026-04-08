# 功能规格说明：风控峰值刹车与双触发闭环

**功能分支**：`codex/008-risk-peak-brakes`  
**创建日期**：2026-04-08  
**状态**：草案  
**输入描述**：Implement peak-based risk brakes with automatic system orders and PM/RT dual triggering.

## 1. 背景与目标

当前系统只有三类硬风控：账户总刹车、单仓从入场价起算的不利波动分级、以及下单/敞口硬上限。它们无法及时管住“多个相关仓位一起小幅回撤，导致账户从盘中高点吐回利润”的场景。

本功能要补齐两层缺口：
- 把单仓风控改成基于单仓自身高点/低点的 trailing 回撤
- 新增组合从当日高点回撤的风险分级，并在 `reduce` / `exit` 时由系统先自动执行风险单，再同时触发 `RT` 和 `PM`

最终目标是让系统在关键时刻先动手，再让 Agent 接棒，而不是把第一反应完全交给 LLM 时延和 Agent timeout。

## 2. 当前系统基线

- `policy_risk` 当前的单仓回撤使用“入场价 -> 当前价”的 adverse move 口径，不是峰值回撤
- 系统不存在“组合从当日高点回撤”的风控状态
- `RT` 已经改为条件触发调度，并通过 `workflow_orchestrator -> openclaw cron run <rt_job_id>` 唤醒
- `PM` 固定班次仍由 OpenClaw cron 承担，当前 `pm-main` 是可直接复用的标准 job
- 执行链已经统一为：`ExecutionDecision -> authorize_execution -> ExecutionPlan -> execution_result`
- 系统当前缺少“系统风控单”这一类自动执行来源，也没有与之对应的 PM 风险重评闭环

## 3. 用户场景与验收

### 场景 1：系统在回撤放大前先自动减风险

当单仓或组合回撤达到 `reduce` 或 `exit` 阈值时，系统先自动减仓/平仓，再让 RT 和 PM 在新的事实基础上继续工作。

**验收标准**

1. 触发 `reduce` 时，系统自动单先进入标准执行链，并在订单记录中可见。
2. 风控单执行后，RT 与 PM 会被同时唤醒；RT 第一轮复查绕过普通 cooldown，PM 稍后出新策略。

### 场景 2：PM 新策略自然接回交易控制权

风险事件发生后，PM 会基于系统已执行的风控动作重新提交策略，而 RT 会在 PM 新策略落库后再次被自然触发，重新接管盘中执行。

**验收标准**

1. `reduce_only` 或 `flat_only` 风险锁在新 PM strategy revision 到来前持续生效。
2. 新 PM strategy revision 落库后，风险锁自动释放，RT 第二次唤醒能够在新 mandate 下继续执行。

## 4. 功能需求

- **FR-001**：系统必须把 `position_observe_drawdown_pct`、`position_reduce_drawdown_pct`、`position_exit_drawdown_pct` 改成单仓自身峰值回撤口径；默认阈值固定为 `0.8 / 1.4 / 2.2`。
- **FR-002**：系统必须新增 `portfolio_peak_observe_drawdown_pct`、`portfolio_peak_reduce_drawdown_pct`、`portfolio_peak_exit_drawdown_pct`，以 UTC 当日高点权益为基准；默认阈值固定为 `0.6 / 1.0 / 1.8`。
- **FR-003**：当单仓进入 `reduce` 时，系统自动对该币减半；当单仓进入 `exit` 时，系统自动对该币全平。
- **FR-004**：当组合进入 `reduce` 时，系统仅对当前浮亏仓位各减半；当组合进入 `exit` 时，系统对所有非零仓位全平。
- **FR-005**：系统风控单必须复用现有执行链和订单记录，不新建独立下单体系；系统单的 `decision_id` 前缀固定为 `risk_reduce_*` 或 `risk_exit_*`，资产级 `actor_role` 固定为 `system`。
- **FR-006**：系统风控单完成后，`workflow_orchestrator` 必须并发触发 RT 和 PM；RT 第一轮用于风险动作复查，PM 负责生成新 strategy revision。
- **FR-007**：RT 的第一次风险复查必须绕过普通 cooldown，但受 `reduce_only` 或 `flat_only` 风险锁约束，不能立即加回风险。
- **FR-008**：PM 新 strategy revision 落库后，沿用现有 `pm_strategy_update -> RT` 路径自然触发 RT 第二轮接棒。
- **FR-009**：风险锁不能依赖固定冷却时间释放；默认只在检测到新的 PM strategy revision 后释放。

## 5. 非功能要求

- **NFR-001**：风控扫描必须是轻量的、非 LLM 的，不得依赖 Agent 推理来决定是否先执行风险单。
- **NFR-002**：风控动作必须是幂等的；相同状态不能在同一上升沿上重复下单。
- **NFR-003**：运行态需要把最近一次风控事件摘要同时暴露给 RT 和 PM runtime pack，以支持后续解释与复盘。

## 6. 关键实体

- **PositionRiskState（单仓风险状态）**：描述单个币当前处于 `normal / observe / reduce / exit` 哪一档，以及该判断对应的峰值参考价、当前回撤和阈值。
- **PortfolioRiskState（组合风险状态）**：描述整个账户相对 UTC 当日峰值权益的回撤状态、峰值权益和阈值。
- **RiskBrakeState（风控刹车状态）**：记录当前 active 风险锁、上一轮已执行的风控动作、锁所绑定的 strategy revision 以及幂等控制信息。
- **RiskBrakeEvent（风控刹车事件）**：记录某次 `observe / reduce / exit` 的触发原因、自动订单摘要、RT/PM 唤醒结果和风险锁模式。

## 7. 假设与约束

- 这次不调整 `max_order_pct_of_exposure_budget`（单笔最大风险预算占比）。
- `panic_exit`（账户总刹车）继续保留，用作账户级灾难刹车，不替代新的组合高点回撤风控。
- 第一版不提供人工解锁机制；风险锁只靠新的 PM strategy revision 释放。
- `reduce` 和 `exit` 的系统自动单属于高风险 live 逻辑，实现上需要可配置开关，并默认保持关闭直到显式启用。

## 8. 成功标准

- **SC-001**：当单仓或组合达到 `reduce` / `exit` 阈值时，系统能在不依赖 RT 先思考的情况下自动完成对应风险单，并留下完整执行记录。
- **SC-002**：RT 与 PM 能在风控动作后看到一致的风控事件摘要，且 PM 新 strategy revision 能自然接回 RT 的第二次执行唤醒。
- **SC-003**：新增风控状态机后，不会破坏现有 PM/RT/MEA/Chief 固定班次、RT 条件触发和标准执行链的兼容性。
