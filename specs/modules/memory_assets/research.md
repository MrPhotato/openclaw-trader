# 研究记录：Memory Assets

## 决策 1：除 learning 外的真实资产统一进 memory_assets

- **Decision**：所有系统真实资产都必须经模块正式接收后写入 `memory_assets`
- **Rationale**：避免模块各自留“私账本”
- **Alternatives considered**：保留多个本地真相源；结论是不利于回放、审计和恢复

## 决策 2：PM 与 MEA 都不自管长期记忆

- **Decision**：PM 和 `MEA` 的长期记忆都只由 `memory_assets` 管理
- **Rationale**：长期真相应只保存正式定稿资产，不保存私有草稿和 transcript
- **Alternatives considered**：保留 Agent 私有记忆；结论是会制造第二真相源

## 决策 3：MEA 记忆只保留语义归并后的结构化事件

- **Decision**：`MEA` 原始新闻不进入长期真相源
- **Rationale**：长期需要的是事件级语义对象，而不是原文堆叠
- **Alternatives considered**：同时存原始新闻和事件；结论是容易造成双重真相

## 决策 4：原生语义记忆只做只读投影

- **Decision**：OpenClaw 原生记忆只读 `memory_assets` 投影
- **Rationale**：保证真相写入权仍然在本地模块
- **Alternatives considered**：允许 Agent 自动捕获写入；结论是违背真相边界
