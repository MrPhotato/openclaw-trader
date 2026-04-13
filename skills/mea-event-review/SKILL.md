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
- 仅在高重要性事件改变当前交易状态时直接通知 `PM` 和 `RT`。
- **同样重要：当事件显著强化 PM 现有 thesis 时（如关键数据超预期确认方向、重大政策利好落地、阻力位被突破），也应通知 PM——让团队有机会考虑加码或扩大敞口带宽。不要只报坏消息，漏报利好和漏报利空一样致命。**
- **你的情报质量决定团队能不能比市场快一步。**

## 工作流
1. 读取 [runtime-inputs.md](references/runtime-inputs.md)。
2. 当批次模糊或影响重大时，按照 [search-playbook.md](references/search-playbook.md) 执行。
3. 按照 [formal-output.md](references/formal-output.md) 输出正式 JSON，并将当前 `input_id` 带回提交桥接。

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
