[English](README.md) | [简体中文](README.zh-CN.md)

# openclaw-trader

`openclaw-trader` 是 OpenClaw 加密交易工作流背后的交易运行时。

它负责：

- 本地 FastAPI 服务和 CLI
- 面向 Agent 的 runtime pack 与 formal submit bridge
- 策略、执行、replay、组合查询接口
- Coinbase INTX 接入
- React/Vite 只读看板

这个仓库是给维护者和开发者看的。运行时状态、密钥、交易所凭证和本地 OpenClaw 配置都放在 git 之外。

## 公开展示页

当前的公开只读看板：

- [https://openclaw-trader.mr-photato.com](https://openclaw-trader.mr-photato.com)

这个站点是刻意设计成只读的。控制接口和 agent 接口仍然只保留在本地运行时。

## 系统形态

系统分成两个明显不同的运行区：

1. 本地交易运行时
   - 运行真正的 trader 服务
   - 连接 OpenClaw、交易所 API 和本地 SQLite 状态
   - 保持 `/api/control/*` 和 `/api/agent/*` 为私有

2. 公网展示层
   - 托管构建后的前端
   - 通过只读查询桥读取数据
   - 在云端带缓存，因此本地短暂断连时页面仍能继续展示最近数据

除非你是在刻意重构安全模型，否则不要把这两层揉到一起。

## 仓库结构

- [src/openclaw_trader](src/openclaw_trader) — 后端应用、模块、适配器和 CLI
- [frontend](frontend) — Vite/React 看板
- [tests](tests) — 后端和集成测试
- [scripts](scripts) — 本地辅助脚本
- [docs](docs) — 维护文档
- [skills](skills) — agent skill 包（PM / RT / MEA / Chief）。可能混有 vendored 第三方 skill（如 [skills/digital-oracle](skills/digital-oracle) — MIT, 源自 [komako-workshop/digital-oracle](https://github.com/komako-workshop/digital-oracle)）；每个第三方 skill 自带 `LICENSE` 与署名。

## 环境要求

- Python `>= 3.11`
- Node.js `>= 18`
- npm
- 一个本地 OpenClaw 运行时
- 放在仓库外的本地配置和密钥

## Git 外的运行时状态

可变运行时状态会刻意存放在当前用户家目录下。

典型本地路径：

- `~/.openclaw-trader/config/`
- `~/.openclaw-trader/state/`
- `~/.openclaw-trader/reports/`
- `~/.openclaw-trader/secrets/`
- `~/.openclaw/`

不要把这些目录提交进 git。

## 后端初始化

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
```

CLI 入口：

```bash
otrader --help
```

常用命令：

```bash
otrader serve
otrader command reset_agent_sessions
otrader workflow --help
otrader strategy --help
otrader portfolio --help
otrader events --help
otrader replay --help
```

## 前端初始化

```bash
cd frontend
npm ci
npm run dev
```

常用前端命令：

```bash
npm run test
npm run build
```

如果后端启动时检测到 `frontend/dist` 已存在，FastAPI 会直接把构建后的前端挂在 `/`。

## 本地开发流程

一个典型开发循环是：

1. 用 `otrader serve` 启动后端
2. 在 [frontend](frontend) 下启动前端 dev server
3. 让前端连本地 API
4. 验证这些只读接口：
   - `/api/query/overview`
   - `/api/query/executions/recent`
   - `/api/query/replay`

开发时要始终区分三件事：

- agent-first 的 runtime pull / submit
- 公网只读展示
- 本地私有控制面

这三者不是一回事。

## 测试

后端测试主要是标准库 `unittest`。

示例：

```bash
uv run python -m unittest tests.test_v2_agent_gateway
uv run python -m unittest tests.test_v2_api_integration
uv run python -m unittest tests.test_v2_workflow_orchestrator
```

前端：

```bash
cd frontend
npm run test
```

## 文档

入口：

- [docs/README.md](docs/README.md)

新维护者建议阅读顺序：

1. [docs/system-overview.md](docs/system-overview.md)
2. [docs/config-and-runtime.md](docs/config-and-runtime.md)
3. [docs/market-intelligence.md](docs/market-intelligence.md)
4. [docs/strategy-and-risk.md](docs/strategy-and-risk.md)
5. [docs/dispatch-and-sessions.md](docs/dispatch-and-sessions.md)
6. [docs/operations.md](docs/operations.md)

补充参考：

- [docs/perps-convergence.md](docs/perps-convergence.md) — legacy / active 路径清单，含 2026-04 SOL 退役
- [docs/prelaunch-readiness.md](docs/prelaunch-readiness.md) — 上线后 gap 跟踪（原上线前 P0/P1/P2 清单）
- [docs/v2-dev-comparison.md](docs/v2-dev-comparison.md) — 与 `codex/dev` 参考运行时的差异

## 安全与公开说明

- 不要提交交易所凭证、OpenClaw 密钥或本地运行时状态
- 不要把 `/api/control/*` 或 `/api/agent/*` 直接公开，除非你额外加了认证和网络隔离
- 把公网看板视为展示层，而不是操盘台
- 如果你要部署公网版本，云端应保持 query-only
