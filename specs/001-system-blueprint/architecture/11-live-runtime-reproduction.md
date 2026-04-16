# 现有 live 运行态复现手册

本文件描述“如果要尽量复现当前系统行为，需要准备哪些运行态事实”。  
它兼容前文 10 模块架构，但重点是现状复刻，而不是未来理想设计。

## 1. 必备目录

当前 live 运行态依赖以下本地目录：

- `~/.openclaw-trader/config/`
- `~/.openclaw-trader/models/`
- `~/.openclaw-trader/reports/`
- `~/.openclaw-trader/state/`
- `~/.openclaw-trader/logs/`
- `~/.openclaw-trader/secrets/`
- `~/.openclaw/`

其中：

- `openclaw-trader` 目录负责交易 runtime
- `.openclaw` 目录负责 OpenClaw gateway、Agent、workspace 与通道路由

## 2. 当前 live 配置快照

### 2.1 交易与执行面

来自 `~/.openclaw-trader/config/` 的当前关键事实：

- `perps.exchange = coinbase_intx`
- `perps.mode = live`
- 跟踪币种：`BTC / ETH`
- dispatcher 扫描周期：`60s`
- strategy 固定刷新时段：`09:00`、`21:00`（`Asia/Shanghai`）
- 模型重训阈值：`360` 分钟
- 当前量化阈值已是放宽后的版本：
  - `history_bars = 6000`
  - `min_confidence = 0.43`
  - `min_long_short_probability = 0.39`
  - `meta_min_confidence = 0.48`
  - `uncertainty_disagreement_caution = 0.32`
  - `uncertainty_disagreement_freeze = 0.45`
  - `uncertainty_regime_fit_caution = 0.30`
  - `uncertainty_regime_fit_freeze = 0.24`

### 2.2 当前启用的新闻源

- Coindesk RSS
- SEC 新闻稿 RSS
- 美联储货币政策 RSS
- 美联储演讲与证词 RSS
- Coinbase status Atom
- FOMC 日历 HTML

### 2.3 当前 owner / 通知路由

当前本地配置表明：

- 主通知渠道使用 `wecom-app`
- owner 目标为本地私有用户路由

具体 token、key、ID 属于私密运行配置，不应写入仓库文档。

## 3. 必须准备但不应入 git 的私有文件

### 3.1 trader 侧

- `~/.openclaw-trader/secrets/coinbase.env`
- 任何带个人 reply channel / owner route 的本地 YAML

### 3.2 OpenClaw 侧

- `~/.openclaw/openclaw.json` 中的网关 token、provider key、通道 secret
- agent 私有配置
- 通道插件私有参数

## 4. 当前运行态产物

### 4.1 报表与记忆

当前系统会持续维护：

- `dispatch-brief.json/md`
- `news-brief-perps.json/md`
- `strategy-day.json/md`
- `strategy-input.json/md`
- `strategy-memory.json/md`
- `strategy-change-log.jsonl`
- `strategy-history.jsonl`
- `position-journal.jsonl`

这些文件不是简单缓存，它们已经承担当前系统的“上下文视图”和“人类可读真相源”角色。

### 4.2 状态库

当前 SQLite 表包括：

- `decisions`
- `risk_checks`
- `orders`
- `news_events`
- `daily_equity_baselines`
- `notification_marks`
- `pending_entries`
- `kv_state`
- `perp_paper_positions`
- `perp_paper_fills`
- `perp_market_snapshots`

其中 `kv_state` 当前还承担了不少调度锁、时间戳和状态标记职责，例如：

- `strategy:last_strategy_date`
- `strategy:last_strategy_slot`
- `strategy:pending_regime_shift`
- `dispatch:last_llm_trigger_at`
- `news:last_sync_at`

## 5. 复现现有行为的最低条件

如果想“行为上尽量像现在”，最低需要同时满足：

1. 当前仓库代码版本
2. 当前 `~/.openclaw-trader/config/*.yaml`
3. 当前 `~/.openclaw-trader/models/` artifact
4. 当前 `~/.openclaw-trader/state/trader.db`
5. 当前 `~/.openclaw/reports` 与 OpenClaw workspace 规则
6. 当前 OpenClaw gateway / channel / agent 配置

只具备仓库代码，无法 1:1 复现当前 live 行为。

## 6. 与未来架构的兼容关系

这份运行态手册在未来模块化后仍然成立，只是会重新映射为：

- 配置与参数治理平面
- 状态与记忆管理模块
- 多智能体协作网关模块
- 通知服务模块

也就是说，未来重构可以改变“代码位置”，但不能丢掉这些运行事实。
