# 上线前任务清单

> **迁移说明（2026-03-15）**：模块与 Agent 的主真相层已迁移到 `specs/modules/` 与 `specs/agents/`。本文档继续作为上线前常驻清单使用，但不再单独承担模块边界与 Agent 工作方式的最高真相源。

本文档是新系统在当前分支上的上线前唯一常驻清单。后续所有“差距分析、补齐项、联调结果、上线阻塞项”都优先更新这里，而不是只留在对话里。

当前目标：
- 以新架构上线
- 保持永续主路径与 `codex/dev` 的关键行为语义一致
- 不回退到旧系统目录结构

当前状态：
- 旧系统已从当前分支移除，仅保留在 `codex/dev`
- 当前代码已收敛为 9 个顶层实现模块，统一落地到 `src/openclaw_trader/modules/`
- `Trade Gateway` 内部继续拆分为 `market_data` 与 `execution`
- 进程内事件总线已落地
- SQLite 状态存储已落地
- v2 回归测试当前通过

## 已达成一致的收敛方向

- `quant_intelligence` 只提供结构化市场事实，不直接输出交易建议。
- `1h/4h/12h` 都作为量化市场事实保留；其中 `1h` 已恢复为 PM 和 RT 的参考信息源，`policy_risk` 仍主用 `4h/12h`。
- `policy_risk` 只保留硬风控，不再维持复杂的软建议型 risk/policy 逻辑。
- `policy_risk` 的第一版最小硬风控参数已经定死：
  - `max_leverage = 5.0`
  - `max_total_exposure_pct = 100.0%`
  - `max_symbol_position_pct = 66.0%`
  - `max_order_pct = 33.0%`
  - `position_risk_state` 阈值为 `4.0 / 7.0 / 10.0`
  - `cooldown = 30` 分钟，仅由 `position_risk_state = exit` 触发
  - `panic_exit = 当日账户权益相对 UTC 00:00 基准下降 15.0%`
  - `breaker = 当日 1 次 panic_exit 或同一 UTC 日内 2 次 position exit，持续到次日 UTC 00:00，支持人工解除或人工延长`
- PM 现在通过 `agent_gateway` 的 `strategy` schema 正式提交目标组合与 recheck 计划，不再依赖独立的 PM 运行模块。
- `TradeCandidate` 已从主链移除；未来由 `Risk Trader` 基于 `ExecutionContext` 产出 JSON 结构化执行决策。
- `Risk Trader` 是高频决策角色，不应被系统预先生成的候选动作过度引导。
- `Trade Gateway` 已取代原 `data_ingest` 与 `execution_gateway` 两个顶层模块，但内部继续保持 `market_data` 和 `execution` 读写分离。
- 第一批主工作流当前已收敛到：`Trade Gateway -> news_events / quant_intelligence -> policy_risk -> agent_gateway runtime inputs`。
- 第一批不让任何 Agent 真跑，不下单，主链停在结构化 `ExecutionContext` 和 Agent 视图。
- `1h` 当前不进入 `policy_risk` 主判断链，但已恢复进入 PM/RT 的上下文参考层。
- `news_events` 的职责已经收敛为：每 `5` 分钟轮询固定源、做轻去重、产出新闻批次并发出 `NEWS_BATCH_READY` 事件。
- `Macro & Event Analyst` 的职责已经收敛为：低频巡检 + 事件驱动唤醒、筛选相关事件、语义归并、将记录压缩到 `1-2` 句话，并在必要时直接与其他 Agent 沟通提醒。
- `Macro & Event Analyst` 的基础触发节奏已经定为：默认每 `2` 小时一次；若收到新闻批次事件，则立即触发并重置 `2` 小时倒计时。
- `memory_assets` 是 `Macro & Event Analyst` 事件记忆的唯一真相源；不再保留独立的 `MEA` 私有记忆文件。
- 除 `learning` 外，系统内所有真实资产统一由 `memory_assets` 书写和管理；Agent 间直接沟通不直接形成系统真相。
- OpenClaw 原生记忆后续只作为 `memory_assets` 的语义检索投影层；`MEA` 不得自写记忆。
- Agent 输出分为“自由沟通”和“正式提交”两条通道：
  - 自由沟通默认允许直接发生，不强制 JSON
  - 正式提交才要求结构化；按角色不同可进一步要求 JSON，例如 `Risk Trader` 的执行决策
- `workflow_orchestrator` 在 `Macro & Event Analyst` 工作流中的职责已收敛为客观唤醒和生命周期管理；不再订阅或转发 `MEA` 的结果内容。
- 未来 `high` 级事件的跟踪预约规则已经定为：
  - 若事件距离当前大于 `5` 小时，则一次性挂 `13` 个任务，覆盖 `event_time - 4h` 到 `event_time + 8h`
  - 若事件距离当前不超过 `5` 小时，则从 `1` 小时以后开始一次性挂 `12` 个任务
  - 当前只保留挂载规则，不提前把正式提交流程绑定给 `workflow_orchestrator`
- `/gemini` 对 `Macro & Event Analyst` 是自由可用的扩搜能力；搜索指令必须以 `Web search for ...` 或 `联网搜索：...` 开头，系统侧不做额外限频。

## P0：上线阻塞项

- [ ] `policy_risk` 按已定稿硬风控规格完成实现收口
  - `observe / reduce / exit`
  - `position_risk_state` 回撤按单位持仓收益/价格路径计算，避免减仓导致虚假放大
  - `cooldown`
  - `panic_exit / breaker`
  - exchange-status 风控

- [ ] `workflow_orchestrator` 补齐自动调度能力
  - 扫描循环
  - 定时策略刷新
  - scheduled recheck
  - daily report
  - fallback
  - 后台长驻运行语义
  - 当前第一批只跑到结构化上下文，不接 Agent / execution / trade notification

- [ ] `agent_gateway` 把 4 Agent 真正接入主工作流
  - PM 第一批仅保留接口，未接主链
  - Risk Trader 第一批仅保留 JSON 回执契约，未接主链
  - Macro & Event Analyst 待接
  - Crypto Chief 待接
  - escalation / session / routing 待补齐

- [ ] `memory_assets` 补齐运行态真相能力
  - 锁与冷却状态
  - strategy 历史
  - scheduled recheck 状态
  - 报表与 journal
  - 更完整的恢复能力
  - `MacroEventRecord / MacroDailyMemory` 的正式落地

- [ ] `Trade Gateway.execution` 补齐执行安全能力
  - preview / 校验
  - 更细的错误分类
  - 幂等与重试策略
  - 更多订单/成交查询能力
  - 执行失败原因统计与聚合视图
  - 当前执行层保留实现和协议，但第一批不在主工作流中运行

- [ ] `notification_service` 补齐上线必需通知链路
  - 策略更新通知
  - 交易事件通知
  - 日报通知
  - 去重 / 冷却 / 重试

## P1：联调重点

- [ ] `quant_intelligence` 与 `codex/dev` 做行为对齐核验
  - artifact 输出
  - retrain 结果
  - horizon 职责
  - 阈值生效结果

- [ ] `Trade Gateway.market_data` 补强容错
  - 单币拉取失败降级
  - 重试与超时
  - 采集异常事件化

- [ ] `Trade Gateway.market_data` 补齐扩展信息面
  - 多尺度 K 线与价格序列
  - 最近 `15m / 1h / 4h / 24h` 压缩价格序列
  - 价格形态摘要
  - 关键价位
  - 突破 / 回踩状态
  - 波动扩张 / 收缩状态
  - 最近订单 / 成交历史
  - 视情况接入最优买卖价 / 订单簿 / 深度
  - 第一批已打通采集与标准化入口，第二批再决定存储与消费方式

- [ ] `news_events` 补强事件治理
  - 去重
  - 生命周期
  - 结构化类别清单
  - 与 `NEWS_BATCH_READY` 的批次输出一致性

- [ ] `Macro & Event Analyst` 接入正式事件工作流
  - `NEWS_BATCH_READY` 触发
  - `2` 小时基础倒计时
  - 语义归并
  - 与 `PM` 的策略影响即时提醒
  - 未来 `high` 级事件的 OpenClaw 托管式预约任务

- [ ] `agent_gateway` 运行时输入编译继续向 skill 化输入靠拢
  - PM 视图
  - Risk Trader 视图
  - Macro 视图
  - Chief 视图

- [ ] `replay_frontend` 补齐前端读模型
  - 实时事件流消费
  - 模块协作时间线
  - 工作流回放
  - 模块状态看板

## P2：工程化优化

- [ ] 拆 `app/dependencies.py`
- [ ] 继续压缩 `quant_intelligence/support/policy.py`
- [ ] 为关键模块补更多异常路径测试
- [ ] 为联调流程补一键 smoke 流程

## 模块状态摘要

### 已经接近可用

- `trade_gateway`
- `news_events`
- `quant_intelligence`

### 还未达到上线要求

- `policy_risk`
- `workflow_orchestrator`
- `agent_gateway`
- `memory_assets`
- `notification_service`
- `replay_frontend`

### 需要联调验证

- `policy_risk`
- `workflow_orchestrator`
- `news_events`
- `memory_assets`

## 使用规则

- 每做完一个上线前任务，就在这里勾掉对应项
- 每发现新的上线阻塞项，就先补到这里
- 若某项决定“不做”，不要直接删除，改成：
  - `[x] 不做：原因`
- 后续如果需要更细的实施拆分，可以在对应 feature 的 `tasks.md` 里展开，但本文件保持上线视角
