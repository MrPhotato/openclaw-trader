# 复盘后行动

按以下顺序执行：

前置条件：
- 仅在 `retro_ready_for_synthesis=true` 时继续
- 如果 briefs 仍在等待中，停止并报告缺失的角色，而不是提交不完整的复盘

1. Owner 摘要
- 向 owner 发送简明的复盘摘要
- **摘要必须明确回答：本周期是否存在明显漏赚的利润空间？**
  - 如果有，根因是什么——PM band 太窄？RT 没用完 discretion？MEA 漏报了利好？
  - 量化估算：如果执行到位，额外利润空间大约多少？
- 不要只报告亏损和风险事件——错过的利润同样是 owner 需要知道的

2. 复盘结果提交
- 使用与 Chief retro pack 中相同的 `input_id` 提交最终复盘结果
- HTTP 请求体**必须包含**：
  - 相同的 `input_id`
  - 非空的 `owner_summary`
  - `case_id`
  - `root_cause_ranking`
  - `role_judgements`
  - `learning_directives` —— 恰好 4 条，覆盖 `pm / risk_trader / macro_event_analyst / crypto_chief`
- 可选字段：
  - `reset_command`
  - `learning_results`

最小可用 payload 范例（省略了 owner_summary / root_cause_ranking / role_judgements 的冗长内容）：

```json
{
  "input_id": "input_xxx",
  "case_id": "retro_case_xxx",
  "owner_summary": "📊 Chief 复盘 2026-MM-DD\n\n...",
  "root_cause_ranking": ["...", "..."],
  "role_judgements": {
    "pm": "...",
    "risk_trader": "...",
    "macro_event_analyst": "..."
  },
  "learning_directives": [
    {
      "agent_role": "pm",
      "directive": "单日同一方向下策略修订上限 2 次，invalidation 触发是唯一例外",
      "rationale": "4/16 一天 8 次修订把 RT 的执行窗口打碎，thesis 方向正确但实际敞口只有目标带的 25%"
    },
    {
      "agent_role": "risk_trader",
      "directive": "开盘 2 小时内用市单把敞口打到目标带下限；实际敞口低于下限 3pp 且 risk normal 时必须补仓",
      "rationale": "4/16 PM 把下限提到 18% 但 RT 停在 8.47%，为了等 $74,500 的 0.6% 价差放弃 10pp 敞口"
    },
    {
      "agent_role": "macro_event_analyst",
      "directive": "同一主题一个 cadence 轮最多 1 条 composite event；补充报道只更新 status 字段不单独成条",
      "rationale": "4/16 8 个 macro_event 里 6 个围绕伊朗叙事，稀释了新事实的权重"
    },
    {
      "agent_role": "crypto_chief",
      "directive": "复盘必须明确识别'高频修订是犹豫伪装'这类模式并在 owner_summary 里点名",
      "rationale": "这种模式披着纪律外衣，若 Chief 不在 retro 里点出来，下一轮 PM 不会自我修正"
    }
  ]
}
```

- 优先编辑 `pull_chief_retro.py` 生成的 `/tmp/chief_retro_submission.json`，然后使用以下命令提交：
  - `python3 /Users/chenzian/openclaw-trader/scripts/submit_chief_retro.py --input-id "$INPUT_ID" --payload-file /tmp/chief_retro_submission.json`
- 先将提交载荷写入本地 JSON 文件，然后 `POST` 该文件
- 如有需要，在提交前直接从已保存的拉取响应中解析顶层 `input_id`
- 永远不要伪造类似 `chief-retro-...` 的本地 id
- 如果学习交付元数据缺失，在最终摘要中明确提及，而不是回退到猜测的会话路由
- **`learning_directives` 缺任何一个角色 = `workflow_orchestrator` 把这一轮 retro cycle 标为 `failed`，下游 learning fingerprint tracking 失效。提交前先 `grep -c agent_role` 确认是 4**

3. 个人学习捕获
- 学习指令用于下游执行，而非同步确认
- 每个 agent 应在其自身会话中稍后使用 `/self-improving-agent`
- 不要因跨会话交付而阻塞复盘提交
- 不要代替 PM / RT / MEA 撰写学习内容

学习内容保存在 `memory_assets` 之外。
