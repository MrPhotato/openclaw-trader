# 运行时输入

## 当前实现
当前运行时路径为：

`OpenClaw 定时或事件唤醒 -> Chief -> AG 拉取桥接 -> 单个 chief-retro pack`

Chief 应从 `agent_gateway` 拉取一个 `chief-retro` 包，然后读取：
- `retro_pack`
- `trigger_context`
- 租约元数据：
  - `input_id`
  - `trace_id`
  - `expires_at_utc`

操作规则：
- 将返回的顶层 `input_id` 视为不透明的租约令牌。
- 如有需要可在本地保存，但不得重命名、重建或用人类可读的占位符替换它。

代码中的权威来源：
- `src/openclaw_trader/modules/agent_gateway/service.py`
- `src/openclaw_trader/app/api.py`

## 目标合约
Chief 应针对以下内容为核心的共享每日包运行复盘：
- `Trade Gateway` 市场和执行时间线
- 关键 `QI` 快照
- 关键 `policy_risk` 变更
- PM 策略版本
- RT 执行批次
- MEA 高影响力事件
- 一个 `retro_case`
- 三份 `retro_briefs`

## 当前使用规则
- 拉取一次，基于该包工作，并使用相同的 `input_id` 提交。
- 优先使用：
  - `python3 /Users/chenzian/openclaw-trader/scripts/pull_chief_retro.py`
  - 该脚本会写入：
    - `/tmp/chief_retro_pack.json`
    - `/tmp/chief_retro_submission.json`
- 最终 `POST /api/agent/submit/retro` 的请求体必须使用与拉取响应中完全相同的顶层 `input_id` 值。
- 提交体必须包含：
  - `input_id`
  - `owner_summary`
- 强烈建议同时包含：
  - `case_id`
  - `root_cause_ranking`
  - `role_judgements`
  - `learning_directives`
- 可选字段：
  - `reset_command`
  - `learning_results`
- 优先使用：
  - `python3 /Users/chenzian/openclaw-trader/scripts/submit_chief_retro.py --input-id "$INPUT_ID" --payload-file /tmp/chief_retro_submission.json`
- 不要在命令行中手动转义长 JSON 体。先写入 JSON 文件，然后 `POST` 该文件。
- 在 owner-summary 阶段，包会提供 `learning_targets[]`，其中包含：
  - 规范化的 `learning_path`
  - 每个 agent 主会话的精确 `session_key`
- 仅使用那些 `learning_targets[].session_key` 值进行学习交付。
- 不要调用 `sessions_list` 来发现或猜测替代的会话名称。
- 如果 `learning_targets[]` 意外缺失，在复盘叙述中注明缺失的元数据，并继续执行，无需等待学习确认。
- 当 Chief 要求 `PM / RT / MEA / Chief` 运行 `/self-improving-agent` 时，必须精确使用所提供的 `session_key`。
- Chief 在此处并非主持实时圆桌会议。
- 包现在提供以下内容：
  - `retro_case`
  - `retro_briefs`
  - `pending_retro_brief_roles`
  - `retro_ready_for_synthesis`
  - `learning_targets`
  - 可选的 `pending_learning_directives`
- 你的任务是评判 case 和那些 briefs，然后输出简明的 Chief 综合报告。
- 如果 `retro_ready_for_synthesis` 为 `false`，停止。不要针对不完整的包进行综合。
