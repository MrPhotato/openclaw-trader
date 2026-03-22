# OpenClaw / Agent 运行手册

本文件补齐“当前系统如何依赖 OpenClaw 与 Agent 运行环境”。

## 1. 当前 OpenClaw 配置位置

主配置文件：

- `~/.openclaw/openclaw.json`

当前关键事实：

- gateway 运行于本地模式
- browser 已启用
- 默认模型来自本地 provider merge 配置
- 已注册 `crypto-chief`、`crypto-chief-manual` 及若干 wecom 用户 agent
- 通道启用 `wecom-app`
- `wechat-access` 当前关闭

私密值如 token、api key、corpSecret 不应入 git。

## 2. 当前与 trader 直接相关的 Agent

### 2.1 `crypto-chief`

- workspace：`~/.openclaw/workspace-crypto-chief`
- agent dir：`~/.openclaw/agents/crypto-chief/agent`
- 用于自动任务、执行判断、策略、日报等主链路协作

### 2.2 `crypto-chief-manual`

- workspace 与 `crypto-chief` 相同
- 但拥有独立 agent id
- 当前用于手动 `strategy-refresh`，避免复用主会话造成上下文污染

## 3. 当前 workspace 事实

`workspace-crypto-chief` 内当前关键文件：

- `AGENTS.md`
- `TOOLS.md`
- `HEARTBEAT.md`
- `MEMORY.md`
- `memory/YYYY-MM-DD.md`
- `.learnings/LEARNINGS.md`

这些文件已经构成当前 Agent 行为的关键部分，不只是附加说明。

## 4. 当前 Agent 行为语义

### 4.1 AGENTS.md

定义：

- 会话开始要读取哪些文件
- 事实优先级
- 交易权限边界
- 手动与自动流程
- stale strategy 的自愈规则
- 输出风格与禁止项

### 4.2 TOOLS.md

定义：

- `otrader` 是唯一合法控制命令
- 当前运行目录、关键配置、关键报表、状态库位置
- 常用控制命令
- 通知风格与边界

### 4.3 HEARTBEAT.md

定义：

- 自动触发来源
- 自动触发时优先读取的 brief
- 静默规则
- 各类通知模板

## 5. 当前 Agent 运行边界

当前单 Agent 体系下，`crypto-chief` 已经承担：

- 策略生成
- 执行判断
- 事件整理
- owner 沟通
- Learning / 复盘

这也是未来拆成 4 Agent 的直接理由。

## 6. 当前 Agent 复现最低条件

若要尽量复现现在 Agent 行为，需要具备：

1. `~/.openclaw/openclaw.json`
2. `~/.openclaw/workspace-crypto-chief/`
3. `~/.openclaw/agents/crypto-chief/agent/models.json`
4. `~/.openclaw/agents/crypto-chief-manual/agent/models.json`
5. `~/.openclaw/logs/`
6. 现有 trader reports 作为上下文源

## 7. 与未来 4 Agent 架构的兼容关系

这份手册的作用不是固化“永远单 Agent”，而是说明：

- 当前行为逻辑已经部分存在于 workspace 文件中
- 未来拆 4 Agent 时，这些规则要拆分、继承或迁移
- 不能只改代码，不迁移 workspace / contract / context view
