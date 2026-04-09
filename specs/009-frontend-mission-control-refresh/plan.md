# 实施计划：Frontend Mission Control Refresh

**功能分支**：`codex/009-frontend-mission-control-refresh`  
**规格文档**：`specs/009-frontend-mission-control-refresh/spec.md`
**计划日期**：2026-04-09

## 1. 执行摘要

本次只重构前端展示层，把当前偏工程化的交易看板收口成公开可读的 live trading floor。实现保持 `frontend/dist` 构建产物、Vite `/api` 代理、FastAPI 静态托管和现有 query-only API 完全兼容，不触碰远端部署链和本地私有 runtime。

## 2. 技术背景（Technical Context）

- **现有系统事实**：前端使用 `React + Vite + TypeScript + Tailwind + React Query + Zustand + Recharts`，主要展示逻辑集中在单一 `frontend/src/app.tsx` 中。
- **目标边界**：重构为 `overview | pm | rt | mea | chief` 五视图，移除 replay 主导航。首页只看系统态，四个席位页各自承接岗位介绍、正式产物摘要与公开阅读语气。
- **主要依赖**：`/api/query/overview`、`/api/query/news/current`、`/api/query/executions/recent`、`/api/query/agents/{role}/latest`、`/api/stream/events`。
- **未知项 / 待确认项**：无阻塞性未知项；展示不足的字段先通过前端派生 view-model 解决，不反推后端接口调整。

## 3. 宪法检查（Constitution Check）

- 模块边界保持不变：仅改 `replay_frontend` 的展示壳，不修改 9+4 主真相层职责。
- 单一真相源保持不变：前端继续只读查询面和事件流，不新增客户端真相或侧写状态。
- 安全渐进式迁移：保留现有部署链、端口、接口和静态托管语义，通过前端内部重构逐步替换旧展示骨架。

## 4. 第 0 阶段：研究与现状归档

- 归档现有远端协作事实：`frontend/dist` 由 GitHub Actions 构建后 rsync 到远端静态目录；本地开发由 Vite 代理 `/api` 到 `127.0.0.1:8788`；FastAPI 检测到 `frontend/dist` 后提供 `/` 静态托管。
- 归档现有前端约束：单页 `app.tsx` 承载导航、数据拉取、布局、图表和格式化逻辑；`Replay` 已不适合作为公开展示入口。
- 吸收 ClawLibrary 灵感，但限定为“活系统感、空间分区、叙事气质”，不引入 Phaser 或游戏式导航。

## 5. 第 1 阶段：设计与契约

- 视图契约收口为 `overview | pm | rt | mea | chief`，`Replay` 退出前端状态与一级导航。
- 展示层拆成页面级 sections 和共享 UI 组件，至少覆盖：`HeroStatus`、`SystemPulse`、`RiskPanel`、`StrategyPanel`、`ExecutionFeed`、`EventWall`、`AgentBoard`。
- 引入前端派生 helper / view-model 层，负责把原始 API 数据转换为公开展示语气、事件优先级、摘要文案和状态提示。
- 只读 API 允许小幅扩展 `/api/query/agents/{role}/latest` 的聚合内容，以承接 RT 战术摘要、Chief 复盘摘要和各席位更可读的最新状态；不触碰 agent pull / submit 热路径。

## 6. 第 2 阶段：任务分解与迁移路径

- 第一步锁定五视图 IA 和 store 契约，确保 replay 从公开入口退出。
- 第二步把首页收口为系统态，把旧的策略 / 事件 / 席位页拆成 PM / RT / MEA / Chief 四个席位页。
- 第三步补齐 RT 战术地图的公开读面，优先使用正式 `rt_tactical_map`，否则退化到只读摘要。
- 第四步把执行展示从“系统日志感”改成“外部可读叙述”，隐藏订单号等不适合公开展示的低价值标识。
- 第五步统一 loading / empty / stale / error 状态、移动端可读性和测试。

## 7. 产物清单

- `plan.md`
- `tasks.md`
