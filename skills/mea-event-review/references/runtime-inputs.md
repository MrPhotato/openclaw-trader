# 运行时输入

## 当前实现
当前运行时路径为：

`OpenClaw cron or event wakeup -> MEA -> AG pull bridge -> single MEA runtime pack`

MEA 应从 `agent_gateway` 拉取一个 `mea` 运行时包，然后读取：
- `news_events`
- `market`
- `macro_memory`
- `trigger_context`
- 租约元数据：
  - `input_id`
  - `trace_id`
  - `expires_at_utc`

代码中的真实来源：
- `src/openclaw_trader/modules/agent_gateway/service.py`
- `src/openclaw_trader/app/api.py`

## 目标合约
目标正式链路保持简单：

`MEA -> AG submit bridge (+ input_id) -> news.schema.json validation -> memory_assets`

高重要性提醒仍通过直接通信发送给 `PM` 和 `RT`。

## 当前使用规则
- 拉取一次，基于该包工作，并使用同一个 `input_id` 提交。
- `market` 仅用于辅助判断事件相关性，不得替代结构化事件推理。
- 唤醒 `PM` 之前，将新事件与以下内容对比：
  - 包中最新的 `PM` 策略，
  - 最新可见的 `PM` 触发上下文，
  - 以及你已就同一主题发送的最近一次直接提醒。
- 仅在状态发生变化时唤醒 `PM`。如果主题、方向和操作含义均未变化，不要再次发送 `PM` 触发。
- 同一主题的重复更新通常应流入正常的 `news` 提交，而非向 `PM` 发送新的 `sessions_send` 中断。
- 唤醒标准是双向的：不仅状态恶化要唤醒 PM，状态显著好转（thesis 被市场数据强力确认、关键阻力被突破、重大利好落地）也要唤醒 PM，让团队有机会加码。
