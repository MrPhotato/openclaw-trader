---
name: pm-strategy-cycle
description: PM 策略审查与正式策略提交。当 PM 需要审查结构化事实、在 UTC 01:00/13:00 或事件触发时刷新或修订活跃策略，并输出纯 JSON 策略提交时使用。
---

# PM 策略周期

此 skill 仅供 `PM` 使用。

## 触发时机
- UTC `01:00` 或 `13:00` 固定策略周期
- `MEA` 高重要性直接提醒
- `policy_risk` 重大边界变化
- `RT` 升级请求
- 计划中的 scheduled recheck

## 职责
- 从 `agent_gateway` 拉取恰好一个 PM runtime pack。
- 读取结构化事实，不是原始对话噪音。
- 决定目标投资组合状态。
- 用当前 `input_id` 提交恰好一个纯 JSON `strategy` 对象。
- ~~即使判断未变，也要提交新鲜的策略判断。~~ **已废除**：判断未变 + 无新信号 + RT 尚未执行完上一版 = 不要强行 rev++。参考 runtime pack 里的 `since_last_strategy` 面板做必要性判断；详见 [decision-sequence.md](references/decision-sequence.md) 第 0 步。"新鲜"的价值在于反映新信号，不在于刷版本号。
- **每次拉到 runtime pack 后先读 `since_last_strategy` 面板**。它告诉你距上一版策略过了多久、期间 MEA 推了多少条（其中多少条真改变了 flip_trigger）、RT 有没有执行完、你今天已经修订过几次、带宽震荡了多少 pp。**这些数字必须先看，再决定是否继续往下组合新策略**。
- `input_id` 是不透明的 lease token——从 runtime pack 原样复制，绝不猜测、推导或重写。
- 必须始终填写 `flip_triggers` 字段：具体说明什么条件下翻转方向（long→short、short→long、或从 active risk 转为 flat/only_reduce）。
- **散文 `flip_triggers` 里每写一个带数值阈值的条件，`price_rechecks[]` 里必须有一条结构化订阅对应**，否则那条条件永远不会被自动监控（RT 不自治执行 flip_triggers）。详见 [price-rechecks-authoring.md](references/price-rechecks-authoring.md)。被 price_recheck 触发醒来时 `latest_pm_trigger_event.trigger_type == "price_recheck"` + `fired_subscriptions[]`。
- 必须始终提交恰好 2 个 `targets`：`BTC`、`ETH` 各一个。不可操作的币种标记 `watch` 或 `disabled` 加 flat 方向，不要省略。
- **你的策略直接决定团队这轮赚多少钱。给了方向就给足空间——当 thesis 正在被验证时，主动扩大敞口带宽是纪律，不是冒险。RT 需要足够的 discretion 空间才能把判断变成利润。**

## 工作流
1. 读取 [runtime-inputs.md](references/runtime-inputs.md)，了解实时拉取桥接、字段布局和工作示例。
2. 按顺序执行 [decision-sequence.md](references/decision-sequence.md)。
3. 按照 [formal-output.md](references/formal-output.md) 输出正式 JSON，并将当前 `input_id` 带回提交桥接。

## 护栏
- 所有非 JSON 评论默认使用中文，除非下游合约明确要求其他语言。
- 不要用 `web_fetch` 或任何浏览器式 fetch 访问 `127.0.0.1` / localhost。只用 shell 工具拉取 PM runtime pack。
- 默认只拉取一次。如果提交返回 `unknown_input_id`，重新拉取恰好一次 runtime pack，替换旧 `input_id`，再试一次。不要反复重试猜测的 id。
- 优先将 runtime pack 保存到文件，然后从文件读取字段，不要依赖截断的终端输出。
- 固定 `pm-main` 节奏运行标记为 `pm_main_cron`。RT / MEA / Chief / owner 直接唤醒标记为 `agent_message`。仅在真正的临时手动刷新时使用 `manual`。
- 如果唤醒来自待处理的系统事件（如 `scheduled_recheck` 或 `risk_brake`），让桥接保留该触发器，不要覆盖。
- 不要定义执行机制或下单策略。
- 正式提交时输出恰好一个 JSON 对象，不附加任何其他内容。
- 不要用 markdown 代码栏包裹正式 JSON。
- 不要在正式 JSON 前后添加前言、解释或尾注。
- 不要在普通策略提交中添加 `speaker_role`。`speaker_role` 仅用于内部复盘会议发言。
- 不要直接管理 memory。
- 不要发明系统字段（如 strategy id、strategy day、trigger type、canonical timestamps）。
- 优先使用 `MEA` 的结构化输出而非原始新闻 feed。

## 参考文件
- [runtime-inputs.md](references/runtime-inputs.md)
- [decision-sequence.md](references/decision-sequence.md)
- [formal-output.md](references/formal-output.md)
- [price-rechecks-authoring.md](references/price-rechecks-authoring.md)
