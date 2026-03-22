# 规格质量检查清单：Policy Risk

**Purpose**：验证硬风控唯一边界被正确固化  
**Created**：2026-03-16
**Feature**：[spec.md](specs/modules/policy_risk/spec.md)

- [x] 已明确 `policy_risk` 只保留硬风控
- [x] 已固化杠杆、敞口、`cooldown`、`panic_exit`、`breaker`
- [x] 未保留 `shadow_policy`
- [x] 已明确 `breaker` 持续时间与人工解除/延长规则
- [x] 已明确 `1h` 不进入 `policy_risk` 主判断链
- [x] 不再保留待讨论的风险语义项
