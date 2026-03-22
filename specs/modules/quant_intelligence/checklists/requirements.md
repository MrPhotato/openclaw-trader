# 规格质量检查清单：Quant Intelligence

**Purpose**：验证量化模块只输出结构化市场事实  
**Created**：2026-03-15  
**Feature**：[spec.md](specs/modules/quant_intelligence/spec.md)

- [x] 已明确 `1h/4h/12h` 计算职责
- [x] 已明确 `1h/4h/12h` 都保留为市场事实，其中 `1h` 当前面向 PM/RT 参考，`policy_risk` 仍主用 `4h/12h`
- [x] 未把建议器语义写回量化模块
