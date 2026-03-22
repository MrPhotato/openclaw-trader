# 部署与进程拓扑手册

本文件描述当前系统如何在本机常驻运行。

## 1. 当前常驻进程管理方式

当前主要通过 macOS LaunchAgents 启动：

- `ai.openclaw.trader`
- `ai.openclaw.trader.dispatcher`
- `ai.openclaw.trader.maintenance`
- `ai.openclaw.gateway`
- `ai.openclaw.wecom-cloudflared`

## 2. 当前 trader 侧进程

### 2.1 trader API

LaunchAgent：

- `ai.openclaw.trader.plist`

启动命令：

- `scripts/run_server.sh`

实际执行：

- 激活 `.venv`
- `uvicorn openclaw_trader.service:app --host 127.0.0.1 --port 8788`

### 2.2 dispatcher

LaunchAgent：

- `ai.openclaw.trader.dispatcher.plist`

实际执行：

- 激活 `.venv`
- `otrader run-dispatcher`

### 2.3 maintenance

LaunchAgent：

- `ai.openclaw.trader.maintenance.plist`

执行时间：

- 每天 `03:35`

## 3. 当前 OpenClaw / 通道侧进程

### 3.1 gateway

LaunchAgent：

- `ai.openclaw.gateway.plist`

当前事实：

- Node 启动
- 本地 gateway 端口 `18789`

### 3.2 wecom cloudflared

LaunchAgent：

- `ai.openclaw.wecom-cloudflared.plist`

当前已观察到本机 `cloudflared tunnel` 常驻进程。

## 4. 当前日志位置

### 4.1 trader 侧

- `~/.openclaw-trader/logs/trader.stdout.log`
- `~/.openclaw-trader/logs/trader.stderr.log`
- `~/.openclaw-trader/logs/trader-dispatcher.stdout.log`
- `~/.openclaw-trader/logs/trader-dispatcher.stderr.log`
- `~/.openclaw-trader/logs/trader-maintenance.stdout.log`
- `~/.openclaw-trader/logs/trader-maintenance.stderr.log`

### 4.2 OpenClaw 侧

- `~/.openclaw/logs/gateway.log`
- `~/.openclaw/logs/gateway.err.log`
- `~/.openclaw/logs/wecom-app-cloudflared.log`

## 5. 当前常用运维命令

- `otrader doctor`
- `otrader dispatch-once`
- `otrader strategy-refresh --reason manual_refresh --deliver`
- `otrader perp-account --coin BTC`
- `otrader perp-model-status --coin BTC`
- `otrader perp-shadow-policy --coin BTC`

## 6. 复现现有部署行为的最低要求

1. 本地 Python 虚拟环境 `.venv`
2. LaunchAgents
3. OpenClaw gateway
4. wecom 通道
5. trader runtime 本地目录
6. 本地 secrets 与 provider key

## 7. 与未来架构兼容方式

未来即使引入 RabbitMQ 与更多模块，仍建议保留：

- trader API / control 面
- dispatcher / workflow worker
- gateway / Agent worker
- 通知与前端各自独立 worker

也就是说，当前部署拓扑可以演进，但不是完全推翻。
