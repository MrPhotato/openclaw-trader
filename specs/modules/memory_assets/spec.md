# 模块规格说明：Memory Assets

**状态**：主真相层草案  
**对应实现**：`src/openclaw_trader/modules/state_memory/`  
**来源承接**：`001`、`007`

## 1. 背景与目标

`memory_assets` 是除 `learning` 外所有真实资产的统一真相源。它负责把模块正式提交和结构化非 Agent 事实持久化、版本化，并向查询、回放和记忆检索提供稳定读面。

## 2. 职责

- 统一持久化运行状态、策略版本、事件记忆、通知结果和回放索引
- 维护 `Macro & Event Analyst` 的事件记忆真相源
- 维护 PM 正式策略资产、revision、supersedes 关系和每币 RT 执行边界约束
- 维护市场运行的 `15m` 轻快照时间线与关键节点全量快照，服务复盘、回放与审计
- 维护投影到 OpenClaw 原生语义检索层的只读视图

## 3. 拥有资产

- `StateSnapshot`
- `StrategyAsset`
- `MemoryView`
- `MacroEventRecord`
- `MacroDailyMemory`
- `MemoryProjection`
- 通知、策略、工作流、回放读模型引用

## 4. 输入

- 业务模块正式提交的结构化资产
- 结构化非 Agent 事实
- `workflow_orchestrator` 的状态和收口记录
- 经 `agent_gateway` 校验后的 `strategy`、`news`、`execution` 正式提交

## 5. 输出

- 按模块和角色可查询的状态、记忆和回放视图
- 面向 Agent 的只读记忆投影

## 6. 直接协作边界

- 接收 `MEA`、`PM`、`policy_risk`、`workflow_orchestrator`、`notification_service` 和执行域正式提交
- 向 `agent_gateway` 运行时输入层、`replay_frontend`、Agent 记忆读取层提供统一读面

## 7. 不负责什么

- 不替代业务模块做判断
- 不允许 Agent 直接写入长期记忆
- 不把聊天 transcript 当作真实资产

## 8. 当前已定

- `MEA` 事件记忆唯一真相源是 `memory_assets`
- 只保存语义归并后的结构化事件，不保存原始新闻
- PM 与 `MEA` 都不自管长期记忆
- PM 只提交策略判断字段；正式策略资产中的 `strategy_id`、`strategy_day_utc`、`generated_at_utc`、`trigger_type` 和最小版本链由系统补齐
- MEA 只提交结构化 `events`；正式 `news_submission` 资产中的 `submission_id` 与 `generated_at_utc` 由系统补齐
- `learning` 仍然完全排除在 `memory_assets` 之外；各 Agent 的复盘 learning 固定按 `.learnings/<agent>.md` 独立存放
- 市场运行快照只保留两类：`15m` 轻快照时间线，以及 PM 新策略、RT 正式决策、execution 提交前后/成交后、风控状态变化、MEA `high` 级提醒、每日复盘冻结点等关键节点的全量快照
- OpenClaw 原生记忆只作为 `memory_assets` 的语义检索投影
- 若启用原生语义记忆，默认 `autoRecall = true`、`autoCapture = false`
- `Crypto Chief` 的复盘 summary 不进入正式资产；各 Agent 的 personal learning 也不进入 `memory_assets`
- 不做 PM 策略的来源链推断，不记录“PM 具体引用了什么”

## 9. 待后续讨论

- 更细的恢复、冷却、journal 与 projection 更新策略
