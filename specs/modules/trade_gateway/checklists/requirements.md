# 规格质量检查清单：Trade Gateway

**Purpose**：验证模块主规格已覆盖职责、资产、输入输出与边界  
**Created**：2026-03-15  
**Feature**：[spec.md](specs/modules/trade_gateway/spec.md)

## Content Quality

- [x] 已明确模块职责
- [x] 已明确拥有资产
- [x] 已明确输入与输出
- [x] 已明确直接协作边界与不负责事项

## Truth Alignment

- [x] 已确认 `Trade Gateway` 是单一顶层模块
- [x] 已确认内部只拆 `market_data` 与 `execution`
- [x] 未把新闻、策略或硬风控重新混回本模块
- [x] `market_data` 已明确结构化 `PortfolioSnapshot`、`ProductMetadataSnapshot` 与未完成订单事实
- [x] 已明确 PM / RT / QI / policy_risk 的运行时事实输入边界
- [x] 已明确 execution 只做已过风控命令的基础送单与技术性重试
