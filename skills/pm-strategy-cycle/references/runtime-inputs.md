# 运行时输入

## 当前实现
当前运行时路径为：

`OpenClaw cron or event wakeup -> PM -> AG pull bridge -> single PM runtime pack`

PM 应从 `agent_gateway` 拉取一个 `pm` 运行时包。

固定 `pm-main` 节奏示例：

```bash
python3 /Users/chenzian/openclaw-trader/scripts/pull_pm_runtime.py \
  --trigger-type pm_main_cron \
  --wake-source openclaw_cron \
  --output /tmp/pm_runtime_pack.json
```

直接消息唤醒示例：

```bash
python3 /Users/chenzian/openclaw-trader/scripts/pull_pm_runtime.py \
  --trigger-type agent_message \
  --wake-source sessions_send \
  --source-role macro_event_analyst \
  --reason "high-impact macro alert" \
  --severity high \
  --output /tmp/pm_runtime_pack.json
```

仅在真正的临时手动刷新时使用 `manual`。如果已有待处理的系统唤醒（如 `scheduled_recheck` 或 `risk_brake`），应让桥接保留该触发器，而不是覆盖它。

此调用并非即时完成。在实时栈中大约需要 `20-30s`，因为桥接会在返回前编译市场、新闻、预测和风控数据。

推荐的提取模式：

```bash
python3 - <<'PY'
import json
from pathlib import Path

pack = json.loads(Path("/tmp/pm_runtime_pack.json").read_text())
print(pack["input_id"])
PY
```

返回的数据结构为：

```json
{
  "agent_role": "pm",
  "task_kind": "strategy",
  "input_id": "input_...",
  "trace_id": "trace_...",
  "trigger_type": "pm_main_cron",
  "expires_at_utc": "2026-03-22T...",
  "payload": {
    "trace_id": "trace_...",
    "decision_context": {
      "regime_summary": "risk_off_with_crypto_headwind",
      "price_snapshot": {"BTC": {"mark": 74200.0, "change_pct_24h": -1.2}, "ETH": {"mark": 2380.0, "change_pct_24h": -1.8}},
      "last_thesis_evidence_breakdown": {"price_action_pct": 40, "quant_forecast_pct": 25, "narrative_pct": 5, "regime_pct": 30},
      "thesis_price_alignment_flag": "aligned",
      "macro_brief_age_hours": 4.5,
      "chief_regime_confidence": "ok"
    },
    "market": {
      "market": {},
      "market_context": {},
      "portfolio": {},
      "accounts": [],
      "execution_history": [],
      "product_metadata": []
    },
    "risk_limits": {},
    "forecasts": {},
    "news_events": [],
    "previous_strategy": {},
    "macro_memory": [],
    "macro_prices": {
      "captured_at_utc": "...",
      "brent": {"price": 90.38, "is_market_open": false, "as_of_utc": "..."},
      "wti": {...},
      "dxy": {...},
      "us10y_yield_pct": {...},
      "btc_fear_greed": {"value": 26, "classification": "Fear"},
      "btc_etf_activity": {"IBIT": {"close": ..., "volume": ..., "avg_volume_20d": ...}, ...}
    },
    "trigger_context": {}
  }
}
```

重要实时字段布局：
- 租约元数据位于顶层：
  - `input_id`
  - `trace_id`
  - `expires_at_utc`
  - `trigger_type`
- 策略事实位于 `payload` 下
- **`payload.decision_context` 是 spec 015 新增的聚合块**，PM 打开 pack 第一步读这里（详见 decision-sequence.md 第 0.a 步）
- `market_context` 和 `portfolio` 位于 `payload.market` **内部**，不是顶层同级字段
- `news_events` 是供 PM 审阅的精简近期新闻层，不是无限制的原始新闻转储
- `latest_pm_trigger_event` 记录本次运行经审计的 PM 唤醒原因。固定节奏、工作流唤醒、直接代理消息和手动刷新都应记录在此
- `latest_risk_brake_event` 在系统刚刚在唤醒 PM 之前强制减仓或平仓时可能存在
- `risk_brake_policy` 描述了常设台面规则：系统监控单仓位最大回撤和组合最大回撤，可以在 PM 被唤醒之前自动减仓或平仓
- `macro_prices` 是 **宏观/大宗商品参考价的权威来源**：Brent/WTI/DXY/US10Y 来自 yfinance（周末/盘后会带 `is_market_open: false` 和较大 `staleness_seconds`），`btc_fear_greed` 每日 00 UTC 更新，`btc_etf_activity` 是 IBIT/FBTC/ARKB 的日成交量 + 20 日均量（不是真 flow 数字，只是机构端活跃度代理）。**禁止用 web_fetch / web_search 抓实时 Brent/WTI/DXY/10Y 价** —— 那些野站数据会翻烙饼，已有过 Rev375→376 那种回滚事故
- `latest_macro_brief`（spec 014）是 Chief 的日频宏观 regime 判断。字段结构：
  - `missing: bool`：系统里还没有 brief（Chief 还没开始日频产出，或资产被清过）
  - `stale: bool`：brief 已过 `valid_until_utc`（默认 generated_at + 36h）
  - `age_hours: float | null`：brief 产出至今多少小时
  - `chief_regime_confidence: "ok" | "low"`：连续 3 份 brief 的 `prior_brief_review.verdict==falsified` 时为 `low`，提示你对 brief 判断打折
  - `brief`：完整 brief 内容，包含 `regime_tags` / `narrative` / `pm_directives` / `monitoring_triggers` / `prior_brief_review` / `data_source_snapshot`
  - **PM 必须在 `portfolio_thesis` 前引用 `brief.regime_tags.regime_summary` 或 `brief.pm_directives`；偏离 brief 时在 `change_summary` 中明示理由**（详见 decision-sequence.md 第 0 步）
  - `missing=true` 或 `stale=true` 时：保守姿态——不扩 band、不切换 portfolio_mode；在 `change_summary` 里写明"brief 缺失/过期，维持保守"
- `previous_strategy` 已使用规范策略字段名称，如：
  - `portfolio_thesis`
  - `portfolio_invalidation`
  - `flip_triggers`
  - `change_summary`
- 不要假设旧的别名如 `thesis` 或 `invalidation`

代码中的权威来源：
- `src/openclaw_trader/modules/agent_gateway/service.py`
- `src/openclaw_trader/app/api.py`

## 目标合约
PM 应继续基于结构化事实工作，但正式输出路径为：

`PM -> AG submit bridge (+ input_id) -> strategy.schema.json validation -> memory_assets + workflow_orchestrator`

PM 不应假设实时路径中存在任何独立的消息代理跳转，也不应假设可以直接从任何消息代理请求数据。

## 当前使用规则
- 拉取一次，基于该包工作，并使用同一个 `input_id` 提交。
- 不要使用 `GET /api/agent/pull/pm` 探测桥接。实时桥接仅支持 `POST`。
- 永远不要使用 `web_fetch` 访问 `127.0.0.1` 或 localhost。仅使用 shell `curl`。
- 优先使用 `python3 /Users/chenzian/openclaw-trader/scripts/pull_pm_runtime.py` 而非手写 curl，以确保 PM 唤醒来源的审计一致性。
- 桥接现在对原始 `pull/pm` 有一个窄安全网：如果 PM 刚刚被最近的直接代理消息唤醒，然后发出一个裸 `pm_unspecified` 拉取请求，服务会继承该最近消息的来源信息，而非静默降级为 `pm_unspecified`。这只是一个防护栏，不是首选路径。
- 不要从时间戳、进程 ID、文件名或部分日志推断 `input_id`。直接从运行时包的顶层读取 `input_id`。
- 由于运行时包输出可能很长，优先将其写入文件再读取文件。不要信任截断的进程输出。
- 拉取运行时包后不要将完整内容粘贴到对话中。将大 JSON 保存在文件中，仅提取需要的字段。
- 如果 `latest_risk_brake_event` 存在，将其视为硬性台面事实：系统已经减仓或平仓。你的任务是重新评估授权并围绕新状态发布新的策略修订。
- 将 `risk_brake_policy` 视为常设内部规则，而非建议。PM 不再是唯一的风控者：系统可以对单仓位最大回撤和组合最大回撤自动减仓或平仓，然后唤醒 PM 修订授权。
- 每个正式策略必须在 `targets` 中明确覆盖 `BTC` 和 `ETH`。不要因为某币种不活跃就省略它；标记为 `watch` 或 `disabled` 即可。
- 如果你被 RT / MEA / Chief / owner 直接唤醒，将唤醒分类为 `agent_message`，并在拉取辅助参数中包含 `source_role`、`wake_source=sessions_send` 和一行 `reason`。
- 如果提交失败并返回 `unknown_input_id`，执行一次新的 `pull/pm`，替换旧的 `input_id`，然后重试一次。到此为止；使用猜测的 ID 反复重试永远是错误的。
- 如果运行时事实和后续设计文档有分歧，以实时包加正式策略合约为准。
- 不要等待 `workflow_orchestrator` 推送策略载荷。PM 现在是代理优先的。
