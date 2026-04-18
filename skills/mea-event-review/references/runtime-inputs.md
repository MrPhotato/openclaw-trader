# 运行时输入

## 当前实现
当前运行时路径为：

`OpenClaw cron or event wakeup -> MEA -> AG pull bridge -> single MEA runtime pack`

MEA 应从 `agent_gateway` 拉取一个 `mea` 运行时包，然后读取：
- `news_events` — 本轮待审查的新闻批次
- `market` — 市场压缩快照（仅用于辅助相关性判断）
- `macro_memory` — 最近的 `macro_daily_memory` 摘要
- `latest_strategy` — **PM 当前生效的策略**（新增）。包含：
  - `strategy_id`, `revision_number`, `generated_at_utc` — 用于识别版本
  - `portfolio_mode`, `target_gross_exposure_band_pct` — PM 的仓位制度
  - `portfolio_thesis`, `portfolio_invalidation` — **核心判断锚点**（MEA 判断事件是否改变状态必读）
  - `flip_triggers` — **PM 明文列出的翻转阈值**（判断 flip_trigger 必读）
  - `targets`, `change_summary`
- `recent_news_submissions` — **你自己最近 3 次 news 提交的摘要**（新增）。每条含：
  - `submission_id`, `generated_at_utc`, `event_count`
  - `events[]` — 每条事件的 `event_id`, `category`, `impact_level`, 截断的 `summary`
  - 用途：判断当前批次是否与近期提交重复，做跨轮去重
- `macro_prices` — 宏观/大宗商品参考价（Brent/WTI/DXY/US10Y + F&G + BTC ETF 活跃度）。判断新闻事件是否已被价格 price in 时用。**禁止 `web_fetch` 抓野站实时大宗价** —— 它们会滚动互相矛盾
- `trigger_context` — 本次唤醒的元信息
- `pending_learning_directive` — Chief 下发的未落实学习指令（如有）
- 租约元数据：
  - `input_id`
  - `trace_id`
  - `expires_at_utc`

代码中的真实来源：
- `src/openclaw_trader/modules/agent_gateway/service.py`（`build_runtime_inputs` 和 `_recent_mea_submissions_digest`）
- `src/openclaw_trader/app/api.py`

## 目标合约
目标正式链路保持简单：

`MEA -> AG submit bridge (+ input_id) -> news.schema.json validation -> memory_assets`

高重要性提醒仍通过直接通信发送给 `PM` 和 `RT`。

## 当前使用规则
- 拉取一次，基于该包工作，并使用同一个 `input_id` 提交。
- `market` 仅用于辅助判断事件相关性，不得替代结构化事件推理。
- 唤醒 `PM` 之前，将新事件与以下内容对比（**现在全部在包里可查，不再靠 session 记忆**）：
  - `latest_strategy.portfolio_thesis` 和 `portfolio_invalidation`——事件是否削弱/强化 thesis？是否触及 invalidation？
  - `latest_strategy.flip_triggers`——事件是否命中任一 flip 阈值？命中 → `thesis_alignment=flip_trigger`。
  - `latest_strategy.target_gross_exposure_band_pct`——事件是否逼迫仓位制度跳档？
  - `recent_news_submissions`——同一 `event_id` 是否已在最近提交中出现？同一主题是否已经唤醒过 PM？
- 仅在状态发生变化时唤醒 `PM`。如果主题、方向和操作含义均未变化，不要再次发送 `PM` 触发。
- 同一主题的重复更新通常应流入正常的 `news` 提交，而非向 `PM` 发送新的 `sessions_send` 中断。
- 唤醒标准是双向的：不仅状态恶化要唤醒 PM，状态显著好转（thesis 被市场数据强力确认、关键阻力被突破、重大利好落地）也要唤醒 PM，让团队有机会加码。
- 当事件确实强化 thesis 时，在 news 提交中用 `thesis_alignment: "reinforces"` 标记——这样 PM 能机器识别"值得加码"而不是靠 summary 文本解析。
