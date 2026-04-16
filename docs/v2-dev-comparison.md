# V2 与 `codex/dev` 对比

本文档记录新 12 模块系统与 `codex/dev` 当前主路径语义的对齐结果。

## 已对齐

- 量化模型周期：`15m`
- `history_bars`：`6000`
- horizon 职责：
  - `12h`：方向锚
  - `4h`：开仓与加仓决策
  - `1h`：仅减仓/延后
- 信号阈值：
  - `min_confidence = 0.43`
  - `min_long_short_probability = 0.39`
  - `meta_min_confidence = 0.48`
- 交易所主路径：`coinbase_intx`
- 支持币种：`BTC / ETH`
- 杠杆上限：`5x`
- 动作集合：`open / add / reduce / close / flip`
- OpenClaw 仍作为外部适配器存在，但边界已收口到 `agent_gateway/adapters/openclaw.py`

## 目标语义

- 新闻仍进入上下文视图与事件模块，不再作为单独的硬阻断入口。
- `workflow_orchestrator` 是唯一主动触发入口。
- 所有跨模块活动都要求产出结构化事件，便于进程内事件总线、回放和前端动画消费。

## 当前实现差异

- 生产适配器仍复用旧 Coinbase / 量化模型实现作为第一版底层适配器。
- 进程内事件总线已经落地，主链正确性依赖 `memory_assets` 与进程内调用，不依赖外部 broker。
- 通知默认已切到真实 `OpenClawNotificationProvider`，由 `openclaw message send` 负责统一外发。
