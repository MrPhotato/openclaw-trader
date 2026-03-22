# 研究记录：Trade Gateway

## 决策 1：顶层上只保留一个 Trade Gateway

- **Decision**：`Trade Gateway` 是单一顶层模块，内部再拆 `market_data` 与 `execution`
- **Rationale**：保持交易所接入边界单一，同时继续维持“读事实”和“写动作”分离
- **Alternatives considered**：恢复为两个顶层模块；结论是会重新打散统一边界

## 决策 2：market_data 负责标准化事实，不负责策略解释

- **Decision**：`market_data` 只输出市场、账户、流动性和执行历史事实
- **Rationale**：避免把事件理解、策略推理和交易所接入混在一起
- **Alternatives considered**：让 `market_data` 直接拼接策略友好字段；结论是应由 `agent_gateway` 的运行时输入编译层负责按角色组装任务输入

## 决策 3：execution 只消费正式执行输入

- **Decision**：`execution` 只消费结构化执行输入并输出交付结果
- **Rationale**：执行层不应私自补全策略或风控语义
- **Alternatives considered**：让执行适配器直接读 prompt 或策略文本；结论是不符合可回放和单一真相源原则
