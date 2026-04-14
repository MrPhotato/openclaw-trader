---
name: chief-retro-and-summary
description: Chief 复盘与 owner 沟通工作流。当 Chief 需要评判每日复盘案例、发出学习指令并发送 owner 摘要时使用。
---

# Chief 复盘与摘要

此 skill 仅供 `Crypto Chief` 使用。

## 触发时机
- Workflow Orchestrator 已准备好 `retro_case` 和全部所需角色 briefs
- Owner 沟通
- 需要时的升级协调

## 职责
- 从 `agent_gateway` 拉取恰好一个 Chief retro pack，优先使用 `scripts/pull_chief_retro.py`。
- 持久保存返回的 pack，以便原样复用其顶级 `input_id`。
- 读取一个 `retro_case` 加三份角色 briefs，然后发出 Chief 综合判断。
- 如果 pack 显示 briefs 仍在等待，到此为止。不要综合、不要发明缺失的 briefs、不要将此拉取变成实时会议。
- 生成面向 owner 的摘要。
- 发出学习指令；每个 agent 稍后通过 `/self-improving-agent` 在自己的 session 中记录学习成果。
- 用当前 `input_id` 提交复盘结果，优先使用 `scripts/submit_chief_retro.py`。
- **你的复盘决定团队是否在重复犯同样的错。尤其注意：方向做对但仓位太小、错过大部分利润——这和止损不执行是同等严重的失败模式。**
- **owner summary 必须明确回答：本周期是否存在明显漏赚的利润空间？如果有，根因是什么？**

## 工作流
1. 读取 [runtime-inputs.md](references/runtime-inputs.md)，了解当前可用素材和目标流程。
2. 按照 [retro-flow.md](references/retro-flow.md) 读取案例、审查 briefs、撰写 Chief 综合判断。
3. 执行 [post-retro-actions.md](references/post-retro-actions.md)，并将当前 `input_id` 贯穿复盘结果提交。
4. 假定 pack 已由 WO 准备好。不要尝试在 Chief session 中重新运行准备工作。

## 护栏
- 所有非 JSON 评论默认使用中文，除非下游合约明确要求其他语言。
- 不要重建同步群聊会议。
- 如果 `pending_retro_brief_roles[]` 非空或 `retro_ready_for_synthesis=false`，不要继续综合。报告复盘准备仍在进行中。
- 不要将每日讨论记录变成正式真相资产。
- 学习文件保持在 `memory_assets` 之外。
- 不要替其他 agent 写学习文件（PM / RT / MEA 的学习由他们自己写）。
- 不要等学习确认就发 owner summary。
- 如果跨 session 投递被禁止或失败，不要通过编辑其他 agent 的文件来绕过。
- 不要退回到 `sessions_list` 或猜测的 session 名称进行学习投递。仅使用 Chief pack 中提供的精确 `learning_targets[].session_key` 值。
- 如果 `learning_targets[]` 意外缺失，声明学习投递元数据缺失，跳过跨 session 投递，仍然完成复盘提交和 owner summary。
- 引用 PM 策略中的未来检查时，将其描述为 PM 制定的计划。
- 不要暗示未来的检查已被系统调度，除非 runtime payload 明确确认了调度器状态。
- 优先使用「PM 安排了下次检查于…」而非「下次 recheck 于…」。
- `POST /api/agent/submit/retro` 必须包含精确的 `input_id` 和非空的 `owner_summary`。
- 可选复盘 payload 字段包括：`case_id`、`root_cause_ranking`、`role_judgements`、`learning_directives`、`reset_command`、`learning_results`。
- 优先使用 repo helpers：
  - `python3 /Users/chenzian/openclaw-trader/scripts/pull_chief_retro.py`
  - `python3 /Users/chenzian/openclaw-trader/scripts/submit_chief_retro.py --input-id ... --payload-file /tmp/chief_retro_submission.json`
- 不要在命令行手动拼接长转义 JSON body。先将最终提交 body 写入本地 JSON 文件，再 `POST` 该文件。
- 回复 runtime 时返回恰好一个 JSON 对象。
- `owner_summary` 必须是非空字符串。
- 绝不发明、转换或摘要 `input_id`——原样复用拉取桥接返回的精确顶级值。

## 参考文件
- [runtime-inputs.md](references/runtime-inputs.md)
- [retro-flow.md](references/retro-flow.md)
- [post-retro-actions.md](references/post-retro-actions.md)
