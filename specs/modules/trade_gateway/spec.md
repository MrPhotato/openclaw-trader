# 模块规格说明：Trade Gateway

**状态**：主真相层草案  
**对应实现**：`src/openclaw_trader/modules/trade_gateway/`  
**来源承接**：`001`、`004`、`005`

## 1. 背景与目标

`Trade Gateway` 是统一的交易所接入边界。顶层上它已经取代旧的“数据接入与标准化”与“账户与下单”双模块拆法，但内部仍必须保持 `market_data` 与 `execution` 两个子域清晰分离。

本模块的目标是：

- 从交易所读取并标准化市场、账户、持仓和执行历史事实
- 接收上游正式执行决策并完成执行交付
- 对下游提供稳定的结构化事实和执行结果，而不是泄露交易所细节

## 2. 职责

- 统一管理交易所公共数据、私有账户数据与执行能力
- 在 `market_data` 子域内产出标准化市场/账户/流动性上下文
- 在 `execution` 子域内把已通过风控的正式执行命令送达交易所
- 在 `execution` 子域内处理交易所技术性重试、回执和失败原因
- 在 `execution` 子域内保留最小执行流水，供审计、回放和复盘学习使用
- 保持“读事实”和“写动作”分离，避免单一子域同时解释世界和推进交易动作

## 3. 拥有资产

- `MarketSnapshotNormalized`
- `AccountSnapshot`
- `PortfolioSnapshot`
- `MarketContextNormalized`
- `ExecutionHistorySnapshot`
- `ProductMetadataSnapshot`
- `ExecutionPlan`
- `ExecutionResult`

## 4. 输入

- 交易所公共市场接口
- 交易所私有账户、订单和成交接口
- 已通过 `policy_risk` 的正式执行命令
- 必要的产品配置、映射和适配器参数

## 5. 输出

- 标准化市场快照、账户快照、组合快照和产品元数据
- 多尺度价格序列、关键价位、突破/回踩、波动状态、流动性快照、最近订单/成交/未完成订单历史
- 执行结果、失败来源、可重放的执行交付记录

## 6. 直接协作边界

- 向 `quant_intelligence`、`policy_risk`、`agent_gateway` 运行时输入层提供事实输入
- 向 PM、`Risk Trader` 和执行链承接所需的正式输入
- 向 `memory_assets` 提交已结构化的市场、账户和执行事实

## 7. 不负责什么

- 不负责新闻采集、事件语义归并和长期事件记忆
- 不负责策略 thesis、目标仓位和组合级再平衡逻辑
- 不负责硬风控检查、审批或策略补全，只消费上游已放行的正式执行命令

## 8. 当前已定

- 顶层模块固定为一个 `Trade Gateway`，不是两个顶层模块
- 模块内部固定拆为 `market_data` 与 `execution`
- `market_data` 第一批必须补齐：
  - `mark/index/funding/premium/OI/24h volume`
  - 账户与持仓风险字段：`entry_price`、`unrealized_pnl`、`liquidation_price`
  - 结构化 `PortfolioSnapshot`
  - `15m/1h/4h/24h` 价格序列、关键价位、突破/回踩、波动状态
  - `best bid/ask`、`spread_bps`、顶层深度摘要
  - 最近订单/成交/失败来源与未完成订单
  - 产品元数据：`tick_size`、`size_increment`、`min_size`、`min_notional`、`trading_status`
- 执行侧只消费结构化正式输入，不自行补全策略含义
- 执行侧不做业务检查；风控检查统一由 `policy_risk` 完成
- RT 正式执行链固定为 `RT -> AG -> policy_risk -> Trade Gateway.execution`
- RT 的最小运行记录归 `Trade Gateway.execution` 所有，不算 RT 记忆
- execution alpha 复盘账只用于 `Chief` 复盘学习，不做实时奖金账
- execution 只做最基础的送单与技术性重试，目标是把已过风控的 RT 意图正确执行到交易所
- execution 不额外承担 preview、复杂执行分类或多交易所抽象
- 面向 `memory_assets` 的市场运行快照只保留 `15m` 轻快照时间线与关键节点全量快照

## 9. 待后续讨论

- 暂无新增待讨论项
