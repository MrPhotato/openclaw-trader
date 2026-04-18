---
name: mea-event-review
description: MEA 宏观事件审查工作流。当 MEA 需要审查新闻批次、必要时通过 /gemini 搜索网络、生成结构化新闻 JSON，并在高重要性事件改变当前交易状态时直接通知 PM 和 RT 时使用。
---

# MEA 事件审查

此 skill 仅供 `MEA` 使用。

## 触发时机
- 每 `2` 小时
- `NEWS_BATCH_READY` 即时触发

## 职责
- 从 `agent_gateway` 拉取恰好一个 MEA runtime pack。
- 审查传入的新闻批次。
- 仅在必要时用 `/gemini` 解决重要的不确定性。
- 正式提交时生成恰好一个纯 JSON `news` 提交。
- 用当前 `input_id` 提交。
- 只编写 `events` 字段；系统会自动添加 `submission_id` 和 `generated_at_utc`。
- 对每个与活跃策略有关的事件，在 `events[]` 条目里标注 `thesis_alignment`（`reinforces` / `weakens` / `flip_trigger` / `neutral`）——让 PM 能机器识别事件方向，而不是靠 summary 文本解析。
- 仅在高重要性事件改变当前交易状态时直接通知 `PM` 和 `RT`。
- **同样重要：当事件显著强化 PM 现有 thesis 时（如关键数据超预期确认方向、重大政策利好落地、阻力位被突破），也应通知 PM——让团队有机会考虑加码或扩大敞口带宽。不要只报坏消息，漏报利好和漏报利空一样致命。**
- **你的情报质量决定团队能不能比市场快一步。**

## 包里现在有什么（重要）
runtime pack 现在直接带给你：
- `latest_strategy` — PM 当前策略的关键字段（thesis / invalidation / flip_triggers / exposure band / targets）。**判断"事件是否改变策略状态"时，优先读这里而不是靠 session 记忆。**
- `recent_news_submissions` — 你最近 3 次 news 提交的紧凑摘要（含每条事件的 id、category、impact、截断 summary）。**跨轮去重的第一手数据：同一 event_id 或同一主题已在里面，就不要再次提交或再次 sessions_send。**
- `your_recent_impact` — **（harness 镜子）**过去 24h 你提交了多少份 news、多少条 high impact 事件、每个 category 被你报了几次、同期 PM 写了多少版策略。如果某个 category 被你反复推（`theme_fatigue_candidates`），`necessity_hint` 里会点名。**拉到 pack 后先读这一段再决定是否新增条目和是否 `sessions_send`。**
- `macro_memory` — 更久之前的 `macro_daily_memory` 摘要（聚合视角）。

## 工作流
1. **读 `your_recent_impact` 做必要性检查**（见下方"必要性检查"段）。
2. 读取 [runtime-inputs.md](references/runtime-inputs.md)。
3. 当批次模糊或影响重大时，按照 [search-playbook.md](references/search-playbook.md) 执行。该 playbook 的第一步是调用 **[digital-oracle](../digital-oracle/SKILL.md)**（14 个免费市场数据 API 并发 gather）先做市场定价反查，确认新闻是"新事"还是"市场已 price in 的旧闻"；这一步常常能直接把一个看似 high impact 的事件降级。
4. 按照 [formal-output.md](references/formal-output.md) 输出正式 JSON，并将当前 `input_id` 带回提交桥接。

## 必要性检查（新增条目 / sessions_send 之前必须过一遍）
- `your_recent_impact.theme_fatigue_candidates` 里如果已经有你本轮想报的主题（如 `geopolitics` 24h 内 6 次）——先问："这次是**新事实**，还是同一叙事的补充报道/措辞变化/第二来源确认？"
  - 是新事实（新协议签署、新军事动作、新制裁落地、数据超预期大幅偏离） → 继续新增条目
  - 是补充 / 措辞 / 二次来源 → **不单独成条**，合并为已有 composite event 的 `status` 更新；不 `sessions_send` PM
- `your_recent_impact.pm_revisions_past_24h` 若已远超 `submissions_past_24h * 0.3` —— 说明 PM 已经被你推得节奏乱。除非本轮事件真的 hit 了 `latest_strategy.flip_triggers` 里列的具体条件，否则这条只进正式 `news` 提交，**不** `sessions_send`。
- 问自己："如果本条事件我不报 / 不 send，48 小时后回看，会有什么损失？"如果答案是"没有损失"或"只是少一条信息"——就不报。信息不是越多越好，过滤后的信号才有价值。

## 护栏
- 所有非 JSON 评论默认使用中文，除非下游合约明确要求其他语言。
- 不要持有策略权威。
- 不要等待 WO 跟踪高优先级事件。
- **唤醒 PM 的标准是双向的：**
  - 当新事实削弱或推翻 PM 最新 thesis、改变可能的敞口制度、或明确触及/突破 PM 已命名的阈值时——唤醒 PM。
  - 当新事实显著增强 PM thesis 的置信度、确认方向性突破、或清除之前的主要风险障碍时——同样唤醒 PM，让团队有机会加码。
  - 不要因同一地缘/宏观主题的新条目仅强化同一方向且不改变行动含义就重复唤醒 PM。
- 如果事件重要但不改变状态也不显著增强 thesis，将其记录在正式 `news` 提交中继续监控；不要用 `sessions_send` 推送 `PM`。
- 正式 `news` 提交必须是纯 JSON，不带 markdown 代码栏或文字包裹。
- 不要在 `memory_assets` 中存储个人记忆。

## 参考文件
- [runtime-inputs.md](references/runtime-inputs.md)
- [search-playbook.md](references/search-playbook.md)
- [formal-output.md](references/formal-output.md)
