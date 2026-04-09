# 任务分解：Frontend Mission Control Refresh

**功能分支**：`codex/009-frontend-mission-control-refresh`  
**规格文档**：`specs/009-frontend-mission-control-refresh/spec.md`

## 第一波：现状拆解与事实归档

- [x] T001 补齐 feature 009 的 `plan.md` 与实施任务，锁定“只改前端展示层、不动远端部署契约”的边界。
- [x] T002 将前端状态契约收口为 `overview | desk | signals | agents` 四视图，彻底移除 replay 在公开展示层的主导航角色。

## 第二波：目标架构与模块契约

- [x] T003 拆分 `frontend/src/app.tsx`，抽出 mission control 页面区块、共享 UI 组件和展示层 helper / view-model。
- [x] T004 重做 `Overview`、`Desk`、`Signals`、`Agents` 四个视图的视觉层级、公开展示文案和状态反馈。

## 第三波：迁移方案与质量门禁

- [x] T005 补齐前端测试，覆盖四视图切换、状态提示、事件流覆盖和 agent 页展示差异。
- [x] T006 运行 `npm test` 与 `npm run build`，确认不破坏 `frontend/dist`、Vite 代理和 FastAPI 静态托管路径。

## 第四波：席位页再次重构

- [x] T007 将公开前端一级信息架构收口为 `总览 + PM + RT + MEA + Chief`，首页只保留系统态，其余页面按 agent 重新组织。
- [x] T008 为 RT 页补齐战术地图公开摘要，并通过 `/api/query/agents/risk_trader/latest` 的只读聚合提供必要数据。
- [x] T009 将执行展示改成可读叙述，移除把订单号作为公开展示重点的旧呈现方式。
- [x] T010 更新前后端测试并再次验证 `npm test`、`npm run build` 与 `pytest` 通过。
