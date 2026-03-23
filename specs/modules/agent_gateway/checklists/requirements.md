# 规格质量检查清单：Agent Gateway

**Purpose**：验证协作层与正式提交通道边界  
**Created**：2026-03-15  
**Feature**：[spec.md](specs/modules/agent_gateway/spec.md)

- [x] 已明确 OpenClaw 是协作层
- [x] 已明确直接沟通与正式提交分离
- [x] 已明确 transcript 不是系统真相
- [x] 已明确 `news` / `strategy` / `execution` 三类正式提交模板
- [x] 已明确 schema 独立存在并参与 prompt 拼接
- [x] 已明确 `strategy` 模板承载 RT 执行边界字段 `rt_discretion_band_pct`
- [x] 已明确每个 Agent 固定单 session，retro 流程不再由 `Chief` 执行 `/new`，统一改由 `workflow_orchestrator` 在每日 `UTC 00:30` 执行
- [x] 已明确 routing 采用静态规则，不做智能路由
- [x] 已明确 schema 校验失败时返回 `schema_ref`、`prompt_ref` 与错误列表，要求重新生成纯 JSON
