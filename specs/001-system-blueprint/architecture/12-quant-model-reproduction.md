# 量化小模型框架、训练与推理复现手册

本文件专门补齐你关心的“量化小模型”部分，并把它放回当前蓝图的模块语义中。

## 1. 它属于哪个模块

当前量化小模型属于：

- `量化判断模块`

但它并不会单独决定是否下单。真正落地时还要经过：

- `风控与执行守卫模块`
- `策略与组合意图模块`
- `状态机与编排器模块`
- `Risk Trader` 执行判断或 fallback

## 2. 当前框架概览

### 2.1 模型结构

当前每个 coin、每个 horizon 都是同一套框架：

- `LightGBM` 方向分类器
- `LogisticRegression` 方向分类器
- 两者做 blended ensemble
- `GaussianHMM` 做 regime
- `LogisticRegression + IsotonicRegression` 做 trade-quality / meta
- 再做 walk-forward calibration，得到可执行 policy

代码主入口在：

- [`pipeline.py`](src/openclaw_trader/market_intelligence/pipeline.py)

## 3. 当前 horizon 与职责

### 3.1 训练 horizon

当前固定训练 3 个 horizon：

- `1h = 4 bars`
- `4h = 16 bars`
- `12h = 48 bars`

前提是 `interval = 15m`。

### 3.2 当前运行职责

当前有效职责是：

- `12h`：方向锚
- `4h`：开仓 / 加仓 / 基础仓位决策层
- `1h`：仅用于已有仓位的减仓 / 延后，不参与新开仓判定

## 4. 当前训练配置

来自 live `model.yaml` 的关键参数：

- `interval = 15m`
- `history_bars = 6000`
- `target_move_threshold_pct = 0.0025`
- `round_trip_cost_pct = 0.0012`
- `min_train_samples = 300`
- `retrain_after_minutes = 360`
- `regime_states = 3`
- `feature_windows = [3, 6, 12, 24, 48]`

## 5. 特征框架

### 5.1 通用价格 / 波动 /量能特征

例如：

- `ret_*`
- `ma_*`
- `ma_spread_*`
- `range_*`
- `drawdown_*`
- `trend_persistence_*`
- `vol_*`
- `volume_z_*`
- `volume_impulse_*`

### 5.2 regime 特征

- `regime_state`
- `regime_confidence`

### 5.3 时间上下文特征

- `time_hour_sin/cos`
- `time_weekday_sin/cos`
- `time_is_weekend`
- `time_session_asia/europe/us`

### 5.4 市场快照特征

- funding
- premium
- open interest change
- day volume change
- snapshot coverage

### 5.5 BTC 参考特征

ETH / SOL 额外带 BTC 参考项：

- `btc_market_*`
- `rel_*_vs_btc`

## 6. 数据与 artifact 目录

当前模型 artifact 位于：

- `~/.openclaw-trader/models/perps/<COIN>/<HORIZON>/`

每个 horizon 至少包含：

- `meta.json`
- `regime.joblib`
- `classifier.joblib`
- `calibration-report.json`
- `calibration-report.md`

## 7. 当前 live artifact 摘要

### 7.1 BTC

- `1h`
  - training rows: `5928`
  - validation accuracy / macro F1: `0.4847 / 0.3814`
  - calibrated global `trade_count = 6`
  - global `objective = -0.244724`
- `4h`
  - training rows: `5916`
  - validation accuracy / macro F1: `0.3864 / 0.3773`
  - calibrated global `trade_count = 0`
  - regime 内 `bearish_breakdown` 为微正
- `12h`
  - training rows: `5884`
  - validation accuracy / macro F1: `0.3956 / 0.3569`
  - calibrated global `trade_count = 1289`
  - global `objective = 1.254324`

### 7.2 ETH

- `1h`
  - rows: `5927`
  - `0.4391 / 0.3824`
  - global `objective = -0.066212`
- `4h`
  - rows: `5915`
  - `0.3925 / 0.3892`
  - global `objective = -0.249861`
  - 但 `bullish_trend` regime 接近可交易
- `12h`
  - rows: `5883`
  - `0.431 / 0.3708`
  - global `objective = 4.371136`

### 7.3 SOL

- `1h`
  - rows: `5927`
  - `0.423 / 0.3851`
  - global `objective = -0.078371`
- `4h`
  - rows: `5915`
  - `0.3841 / 0.3498`
  - global `objective = 1.396227`
- `12h`
  - rows: `5883`
  - `0.4147 / 0.3369`
  - global `objective = -0.066325`
  - 但部分 regime 有正 edge

## 8. 当前训练入口与使用入口

### 8.1 训练入口

CLI：

- `otrader perp-model-train --coin BTC`
- `otrader perp-model-train --coin BTC --all-horizons`

代码上由 `PerpModelService.train_models()` / `train_all_horizons()` 承担。

### 8.2 推理入口

当前推理不是单独服务，而是在运行时按需触发：

- `PerpModelService.ensure_models()`
- `predict_multi()`
- `model_status()`

dispatcher 每轮评估都会重新消费模型，但不一定重训模型。

## 9. 当前“如何被用到”

模型输出并不会直接变成订单。当前链路是：

1. 模型产出 `1h/4h/12h` 结构化判断
2. policy 聚合出硬风控边界
3. 风控与执行守卫再叠加事件、组合、不确定性
4. 策略模块生成目标仓位
5. runtime 判断是否出现合法 candidate
6. Risk Trader 做执行判断
7. 执行模块下单

## 10. 当前复现实操注意点

### 10.1 只复制代码无法复现当前模型行为

还需要：

- 当前 `model.yaml`
- 当前 `perp_market_snapshots`
- 当前 models artifact
- 当前训练数据覆盖窗口

### 10.2 不要只看 accuracy

当前实战里，更重要的是：

- `trade_count`
- `objective`
- `avg_net_return`
- 各 regime calibration

### 10.3 当前策略经验

截至目前的已验证经验是：

- `1h` 不适合当开仓硬门槛
- `12h` 更适合做方向锚
- `4h` 更适合做执行层决策
- 硬风控边界才是 LLM 与执行真正需要服从的边界

## 11. 与未来架构兼容方式

未来重构时，这套小模型框架可以保持不变，但必须：

- 被明确收口到量化判断模块
- 把训练、artifact、校准、推理、诊断接口显式化
- 不再把 policy translation 和 execution guard 混进同一大文件
