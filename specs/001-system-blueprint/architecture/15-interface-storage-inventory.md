# 当前接口与数据载体清单

本文件补齐“现有功能是否能被完整追踪”的最后一块：接口与数据载体。

## 1. 当前操作接口

### 1.1 CLI

当前最关键的 CLI：

- `otrader doctor`
- `otrader dispatch-once`
- `otrader strategy-refresh --reason manual_refresh --deliver`
- `otrader strategy-show`
- `otrader perp-snapshot --coin BTC|ETH|SOL`
- `otrader perp-account --coin BTC|ETH|SOL`
- `otrader perp-signal --coin BTC|ETH|SOL`
- `otrader perp-shadow-policy --coin BTC|ETH|SOL`
- `otrader perp-model-status --coin BTC|ETH|SOL`
- `otrader perp-model-train --coin BTC|ETH|SOL [--all-horizons]`
- `otrader maintenance`

### 1.2 FastAPI

当前关键 HTTP 接口：

- `/healthz`
- `/news`
- `/workflow`
- `/perps/snapshot`
- `/perps/account`
- `/perps/open-paper`
- `/perps/close-paper`
- `/perps/open-live`
- `/perps/panic-lock`
- `/perps/panic-resume`
- `/autopilot-check`
- `/daily-report`

## 2. 当前数据载体

### 2.1 SQLite

当前 SQLite 承担：

- 决策记录
- 风险检查
- 订单结果
- 新闻事件
- 基线权益
- pending entry
- `kv_state`
- paper positions / fills
- perp 市场快照

### 2.2 reports

当前 reports 承担：

- 人类可读上下文
- 策略版本与当日策略
- dispatch 临场快照
- strategy input / memory
- journal 与历史轨迹

### 2.3 logs

当前 logs 承担：

- 低层错误
- 进程异常
- 网络问题
- OpenClaw / 通道路由异常

## 3. 当前“复现现有功能”时哪些必须一起保留

若要尽量复现现有功能，而不是只复现代码结构，需要同时保留：

- CLI / FastAPI 面
- SQLite
- reports
- model artifacts
- runtime YAML
- OpenClaw workspace / gateway

少其中任一项，系统都只能“部分复现”。

## 4. 与未来架构的对应关系

未来应当把这些载体重新归类：

- CLI / HTTP -> 状态机与编排器模块的适配层
- SQLite / reports -> 状态与记忆管理模块
- model artifacts -> 量化判断模块
- OpenClaw workspace / agent config -> 多智能体协作网关模块
- logs -> 结构化事件与日志平面 + 低层运维日志
