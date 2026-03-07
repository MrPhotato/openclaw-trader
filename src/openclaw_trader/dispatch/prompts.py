from __future__ import annotations

from pathlib import Path

EVENT_PROMPT = (
    "执行一次由本地事件触发器命中的 crypto-chief 巡检。"
    "忽略聊天上下文，先读取 ~/.openclaw-trader/reports/dispatch-brief.md、~/.openclaw-trader/reports/news-brief-perps.md、~/.openclaw-trader/reports/strategy-day.md，"
    "把它们当作本次主要记忆源。"
    "如果 dispatch-brief.md 里已经包含 LLM 审核结果或执行结果，以它为准。"
    "必要时再用本机交易运行时 otrader 核验。"
    "这次已经命中可通知事件，必须输出 1 条可直接发给用户的结果。"
    "严格按 HEARTBEAT.md 输出，不要改写固定模板。"
    "输出必须是微信纯文本，第一行必须以🔵开头。"
    "严禁输出 JSON、代码块、花括号或原始结构化对象。"
    "若本轮已执行任何成交（含 open/add/reduce/close/flip），必须优先使用🔵💰成交模板；无成交时再使用🔵👀。"
    "绝不允许回复 HEARTBEAT_OK。"
)

FALLBACK_PROMPT = (
    "执行一次 crypto-chief 兜底巡检。"
    "忽略聊天上下文，先读取 ~/.openclaw-trader/reports/dispatch-brief.md、~/.openclaw-trader/reports/news-brief-perps.md、~/.openclaw-trader/reports/strategy-day.md，"
    "把它们当作本次主要记忆源。"
    "必要时再用本机交易运行时 otrader 核验。"
    "若无事发生，仅回复 HEARTBEAT_OK。"
)

DAILY_REPORT_PROMPT = (
    "执行 crypto-chief 晚报。"
    "忽略聊天上下文，先读取 ~/.openclaw-trader/reports/dispatch-brief.md、~/.openclaw-trader/reports/news-brief-perps.md、~/.openclaw-trader/reports/strategy-day.md。"
    "必要时再用本机交易运行时的 otrader daily-report 核验。"
    "在输出给用户前，先调用一次 self-improving-agent skill 做当日复盘学习，"
    "并把学习记录写入当前 workspace 的 learning（.learnings/LEARNINGS.md）。"
    "如果 skill 不可用，至少追加 1 条简短学习记录到 .learnings/LEARNINGS.md。"
    "按固定模板输出，不要追加说明。"
)

STRATEGY_PROMPT = (
    "你在刷新 crypto-chief 的当日战略。"
    "忽略聊天上下文，先读取 ~/.openclaw-trader/reports/strategy-input.md、~/.openclaw-trader/reports/strategy-memory.md、~/.openclaw-trader/reports/news-brief-perps.md，"
    "若存在再读取 ~/.openclaw-trader/reports/strategy-day.md。"
    "请仅输出一个 JSON 对象，不要 Markdown，不要代码块，不要额外解释。"
    "字段必须包含：strategy_date, market_regime, risk_mode, soft_min_leverage, soft_max_leverage, summary, invalidators, symbols。"
    "risk_mode 默认应写 aggressive；只有当你有明确证据认为当天应收缩风险时，再改写为 normal 或 defensive。"
    "可选字段：scheduled_rechecks。"
    "symbols 必须是数组，每项包含：symbol, bias, max_position_share_pct, thesis。"
    "bias 只能是 long / neutral / short / avoid。"
    "如果 bias 是 neutral 或 avoid，对应 symbol 的 max_position_share_pct 必须是 0。"
    "优先参考 strategy-input.md 里的 LightGBM 信号、HMM regime、validation 指标。"
    "当 signal=flat 时，不要把所有 flat 都当成同一种情况；请结合 strategy-input.md 里的 signal_context 区分 true_flat、direction_pending、breakout_watch。"
    "true_flat 默认维持 0%；direction_pending / breakout_watch 则应在 thesis 或 summary 里明确说明是在等方向确认，而不是笼统写成没有机会。"
    "soft_min_leverage / soft_max_leverage 表示你当天建议的软杠杆区间。"
    "soft_min_leverage 不得低于 1；soft_max_leverage 不得低于 soft_min_leverage，且绝不能超过 strategy-input.md 里的硬杠杆上限。"
    "max_position_share_pct 表示该品种的建议目标仓位，占硬总敞口预算的份额百分比，不是占账户权益的百分比。"
    "上述 share 按保证金口径理解；实际名义仓位=保证金金额 × 执行杠杆。"
    "strategy-input.md 里给出的参考目标仓位区间只是基线参考，不是配额，也不是硬上限；你可以根据证据自由调整目标仓位。"
    "对于已经形成方向但质量一般的 directional 信号，不要机械归零；应优先考虑 10%-20% 或 20%-40% 这样的中间档，而不是只有最强信号才给仓位。"
    "单笔执行只受 strategy-input.md 里的全局单笔硬上限约束，不需要为每个 symbol 单独输出单笔上限。"
    "你的职责是给出最终想持有的目标仓位，而不是为后续确认预留阶段性仓位。"
    "如果你认为当前机会质量明显强于或弱于基线，可直接体现在 max_position_share_pct 上，并在 thesis 或 summary 里用文字说明临场判断，无需新增字段。"
    "若多个币同时满足高等级信号，应主动做主次排序，不要求机械把所有品种同时打到参考区间上沿。"
    "但只要某个目标仓位在当前硬总敞口预算下会落到 minimum_trade_notional_usd 以下，就必须把这个 symbol 写成 0，而不是写一个不可执行的小百分比。"
    "如果你认为某个未来事件需要在临近时再次重审战略，可输出 scheduled_rechecks 数组。"
    "scheduled_rechecks 每项必须包含：fingerprint, event_at, run_at, reason。"
    "这表示你预约未来一次 strategy 重审；run_at 必须是未来时间。"
    "如果你认为跟踪范围需要增删，请可选输出 watchlist_suggestions={add:[...],remove:[...],reason:\"...\"}，但这只是建议，不会自动生效。"
    "这是一份当日战略，可以根据重大新闻覆盖旧版本。"
)

TRADE_REVIEW_PROMPT = (
    "你在做 crypto-chief 的单次交易审核。"
    "忽略聊天上下文，先读取 ~/.openclaw-trader/reports/dispatch-brief.md、~/.openclaw-trader/reports/news-brief-perps.md、~/.openclaw-trader/reports/strategy-day.md、~/.openclaw-trader/reports/strategy-memory.md。"
    "小模型信号和 HMM regime 只是证据，不是最终拍板者。"
    "你要结合当日战略、近期新闻、当前仓位与风控状态，对 dispatch-brief.md 中列出的全部 trade candidates 做最终判断。候选可能是 open / add / reduce / close / flip。"
    "默认以靠拢当日 strategy target 为基线；如果你判断临场机会质量偏弱，可缩量或观察；如果机会质量更好，可完整执行候选，并在 reason 里说明临场判断。"
    "请仅输出一个 JSON 对象，不要 Markdown，不要代码块，不要额外解释。"
    '字段必须包含：decision, reason, orders。'
    '顶层 decision 只能是 approve / reject / observe，表示你对本轮组合动作的总体判断。'
    'orders 必须是数组，顺序就是执行顺序。每项必须包含：product_id, decision, size_scale, reason。'
    'orders[*].decision 只能是 approve / reject / observe。'
    "size_scale 是 0 到 1 的浮点数；只有 approve 时可以大于 0，且不能放大超过本地建议仓位。"
    "若某个 order 的 decision=approve，尽量额外给出 stop_loss_price、take_profit_price、exit_plan。"
    "stop_loss_price 和 take_profit_price 都用绝对价格，不要用百分比。"
    "exit_plan 用一句话说明失败条件、主动止盈/止损思路或临场退出原则。"
    "这些字段当前只用于记录、复盘和后续 AI 参考，不会在本轮自动下到交易所。"
    "只对 dispatch-brief.md 中出现的 trade candidates 逐项输出 orders；不想执行的候选也要保留在 orders 中并给 reject 或 observe。"
)

STRATEGY_NOTIFY_PROMPT = (
    "你是 owner 的主Agent。crypto-chief 刚更新了当日永续战略。"
    "忽略聊天上下文，先读取 ~/.openclaw-trader/reports/strategy-day.md。"
    "不要把这个任务再转给 crypto-chief。"
    "请用简洁中文推送 1 条摘要到微信。"
    "首行标题必须以“策略更新”开头。"
    "不要使用“日报”“晚报”“周报”等字样。"
    "必须包含：市场判断、风险档位、软杠杆区间、BTC/ETH/SOL 的 bias 与建议目标仓位。"
    "如果 strategy-day.md 中存在跟踪范围建议，也要用一句话带上。"
    "不要展示止损价、止盈价、退出计划等订单级细节；这些只在具体订单通知里展示。"
    "不要表格，不要长篇分析。"
)

DAILY_STRATEGY_SLOT_LOCK_PREFIX = "strategy:daily_strategy_inflight:"

WECOM_NAMESPACE_REGISTRY = Path.home() / ".openclaw" / "wecom-app" / "user-namespaces.json"
