# 复盘流程

首选复盘窗口：
- 在 WO 准备好 `retro_case + retro_briefs` 之后

将复盘作为异步判断流程执行，而非实时会议。

工作顺序：

1. 读取 `retro_case`
- 理解目标：
  - 桌面为什么没能赚到 `1%`
  - **桌面方向做对了但仓位太小、错过大部分利润的情况同样重要——这和做错方向是对等的失败**
  - 明确的挑战提示是什么

停止条件：
- 如果 `retro_case` 缺失，或 `pending_retro_brief_roles[]` 非空，立即停止
- 不要自行创建替代 briefs
- 不要将复盘转变为同步圆桌会议

2. 读取全部三份角色 briefs
- `pm_retro_brief`
- `rt_retro_brief`
- `mea_retro_brief`

3. 评判 briefs
- 识别谁看对了方向
- 识别谁过于防守、过于迟缓、或噪音过多
- **识别谁在方向正确时仓位过小，导致团队没有把判断变成利润**
- 区分：
  - 信号质量
  - 执行质量（包括是否充分利用了 discretion 空间）
  - 流程质量
  - 运气

4. 撰写 Chief 综合报告
- `owner_summary` —— 必须明确回答"本周期是否存在漏赚/失误，根因是什么"
- `root_cause_ranking` —— 按影响力排序，最多 5 条
- `role_judgements` —— `{pm, risk_trader, macro_event_analyst}` 三个字段的叙事判断
- `learning_directives` —— **恰好 4 条**，分别对应 `pm / risk_trader / macro_event_analyst / crypto_chief`；每条是 `{agent_role, directive, rationale}`。这是结构化跟踪通道的主键，少一条下游 cycle 就会 `failed`。内容要求：
  - `directive`：一句可执行的铁律（例如 "单日策略修订上限 2 次"、"开盘 2 小时内市单打到目标带下限"），不是描述问题
  - `rationale`：为什么这次的事件证明需要这条铁律（一到两句话，指向具体数据点）
  - crypto_chief 自己也要有一条 —— 通常是"本 Chief 下次复盘时必须点名的模式"

方法：
- 默认使用「事实回顾 -> 根因判断 -> 后续修正」结构
- 仅在重大失败时使用「连续追问根因」的方法
- narrative（`role_judgements`）和 structured（`learning_directives`）必须一致：`role_judgements` 里给谁写了改进方案，`learning_directives` 里就要为谁出一条 directive。省略等于让结构化跟踪失效。
