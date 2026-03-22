# 规格质量检查清单：Crypto Chief

**Purpose**：验证 Chief 的 owner-facing 与升级职责  
**Created**：2026-03-15  
**Feature**：[spec.md](specs/agents/crypto_chief/spec.md)

- [x] 已明确 owner 沟通、复盘、Learning、升级协调职责
- [x] 已明确不替代下级 Agent 一线职责
- [x] 已明确不成为系统唯一真相源
- [x] 已明确各 Agent 的个人 learning 固定分文件记录，不混写到共享 learning 文件
- [x] 已明确 Chief 遵循方法论主持复盘，但不强制固定模板
- [x] 已明确复盘结束后 Chief 发出 learning 指令并提交会议总结，`/new` 改由 `workflow_orchestrator` 在每日 `UTC 00:30` 统一执行
