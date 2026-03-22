# 一致性分析

本文件用于检查 `spec.md`、`plan.md`、`tasks.md`、`architecture/` 与 `contracts/` 是否相互一致。

## 1. 规格到设计的映射

| 规格需求 | 对应设计文档 | 结论 |
| --- | --- | --- |
| FR-001 当前系统基线 | `architecture/00-current-system-baseline.md` | 已覆盖 |
| FR-002 10 模块定义 | `architecture/01-target-architecture.md`、`architecture/02-module-inventory.md` | 已覆盖 |
| FR-003 3 条跨域平面 | `architecture/01-target-architecture.md`、`architecture/05-rabbitmq-topology.md`、`architecture/07-logging-replay-frontend.md` | 已覆盖 |
| FR-004 4 个 Agent | `architecture/06-agent-topology.md`、`contracts/openclaw-gateway.md` | 已覆盖 |
| FR-005 LLM 信息源 | `architecture/03-information-sources.md` | 已覆盖 |
| FR-006 统一状态机 | `architecture/04-state-machine.md` | 已覆盖 |
| FR-007 统一主动触发入口 | `architecture/04-state-machine.md`、`contracts/external-control-api.openapi.yaml` | 已覆盖 |
| FR-008 对外接口与 OpenClaw | `architecture/08-external-interfaces.md`、`contracts/openclaw-gateway.md` | 已覆盖 |
| FR-009 模块接口与消息协议 | `contracts/module-ports.md`、`contracts/rabbitmq-routing.md`、`contracts/event-envelope.schema.json` | 已覆盖 |
| FR-010 日志、回放与前端 | `architecture/07-logging-replay-frontend.md` | 已覆盖 |
| FR-011 迁移波次与任务 | `architecture/09-migration-waves.md`、`tasks.md` | 已覆盖 |
| FR-012 复现级文档 | `architecture/11-live-runtime-reproduction.md`、`architecture/12-quant-model-reproduction.md`、`architecture/13-openclaw-agent-runtime.md`、`architecture/14-deployment-topology.md`、`architecture/15-interface-storage-inventory.md` | 已覆盖 |

## 2. 计划到任务的映射

| 计划阶段 | 任务项 | 结论 |
| --- | --- | --- |
| 第 0 阶段：现状归档 | T001-T003 | 已映射 |
| 第 1 阶段：设计与契约 | T004-T008 | 已映射 |
| 第 2 阶段：迁移与质量门禁 | T009-T012 | 已映射 |

## 3. 文档之间的一致性结论

### 3.1 已确认一致

- 10 模块、3 条跨域平面、4 个 Agent 在所有核心文档中保持一致。
- “统一主动触发入口归属于状态机与编排器模块”在规格、状态机文档与 OpenAPI 契约中保持一致。
- “RabbitMQ 是跨域平面，不是顶层业务模块”在目标架构、消息拓扑和契约中保持一致。
- “结构化事件与日志平面支撑前端动画、回放与审计”在目标架构、日志前端文档与事件 schema 中保持一致。
- 新增的复现级文档没有另起一套架构术语，而是继续依附于 10 模块与 3 条平面。

### 3.2 当前仍保留的实现期开放项

- 事件持久化最终是否继续以 SQLite 为主，还是演进到独立事件存储，在实现期仍可再评估。
- 前端读模型是否需要单独查询服务，当前蓝图只规定了接口边界与数据形态，还未定死实现栈。
- 多 Agent 的具体 prompt / workspace 结构未在本轮蓝图中展开到文件级模板，这是实现期任务。
- 本轮文档已经记录 OpenClaw workspace 与 agent 运行事实，但没有把未来 4 Agent 的每份 workspace 文件模板逐一写出来，这仍属于实现期设计。

### 3.3 不视为问题的刻意留白

- 蓝图没有直接重写现有代码结构，这是有意为之。
- 蓝图没有强行承诺某个前端框架或部署形态，这是为了先稳住边界与协议。

## 4. 质量门禁结论

基于当前文档状态：

- 未发现残留占位符
- `external-control-api.openapi.yaml` 可被 YAML 解析
- `event-envelope.schema.json` 可被 JSON 解析
- speckit 初始化脚本可正常识别当前 feature 目录与核心文档

## 5. 建议的下一步

1. 先按 `tasks.md` 进入“骨架波次”，不要直接大改所有业务代码。
2. 先实现统一事件协议、状态机骨架和 RabbitMQ 总线，再拆 `dispatch` / `strategy` / `runtime`。
3. 多 Agent 化应在状态机与上下文视图稳定后推进，避免把当前边界问题直接复制到更多 Agent 上。
