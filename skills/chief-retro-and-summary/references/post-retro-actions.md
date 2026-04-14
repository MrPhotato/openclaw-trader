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
- HTTP 请求体必须包含：
  - 相同的 `input_id`
  - 非空的 `owner_summary`
- 强烈建议同时包含：
  - `case_id`
  - `root_cause_ranking`
  - `role_judgements`
  - `learning_directives`
- 可选字段：
  - `reset_command`
  - `learning_results`
- 优先编辑 `pull_chief_retro.py` 生成的 `/tmp/chief_retro_submission.json`，然后使用以下命令提交：
  - `python3 /Users/chenzian/openclaw-trader/scripts/submit_chief_retro.py --input-id "$INPUT_ID" --payload-file /tmp/chief_retro_submission.json`
- 先将提交载荷写入本地 JSON 文件，然后 `POST` 该文件
- 如有需要，在提交前直接从已保存的拉取响应中解析顶层 `input_id`
- 永远不要伪造类似 `chief-retro-...` 的本地 id
- 如果学习交付元数据缺失，在最终摘要中明确提及，而不是回退到猜测的会话路由

3. 个人学习捕获
- 学习指令用于下游执行，而非同步确认
- 每个 agent 应在其自身会话中稍后使用 `/self-improving-agent`
- 不要因跨会话交付而阻塞复盘提交
- 不要代替 PM / RT / MEA 撰写学习内容

学习内容保存在 `memory_assets` 之外。
