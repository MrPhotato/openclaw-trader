# 功能规格说明：Frontend Mission Control Refresh

**功能分支**：`codex/009-frontend-mission-control-refresh`  
**创建日期**：`2026-04-09`  
**状态**：草案  
**输入描述**：移除回放入口，继续重做前端一级信息架构，把首页收成系统总览，并把后续页面改成 PM / RT / MEA / Chief 四个席位页。RT 页需要承接战术地图；执行内容必须改成供人阅读的公开叙述，不再把订单号等低价值内部标识暴露给前端外部观众。

## 1. 背景与目标

当前前端已经能读 `overview / executions / news / agent latest`，但整体更像“能展示数据的 demo 看板”，而不是“当班操作员第一眼就知道该看什么、该不该干预”的交易指挥台。顶部文案、导航层级、状态反馈和重点信息排序都不够锋利。

本 feature 的目标不是推倒现有前端栈，而是在保留 `Vite -> frontend/dist -> GitHub Actions -> 远端静态目录` 这条部署链和现有 `/api/query/*` 读接口不变的前提下，把前端收口成更成熟的 operator UI。

## 2. 当前系统基线

- 前端是独立 `React + Vite + TypeScript + Tailwind + React Query + Zustand` SPA。
- 开发环境通过 Vite 将 `/api` 代理到本地 `127.0.0.1:8788`。
- 本地后端若检测到 `frontend/dist` 存在，会直接托管构建产物。
- 公网展示通过 GitHub Actions 构建 `frontend/dist` 并 rsync 到远端静态目录；控制和 agent 提交接口保持在本地私网 runtime。
- 当前一级导航包含 `回放`，但它更接近调试/审计能力，不适合作为主操作导航。

## 3. 用户场景与验收

### 场景 1：值班时快速判断系统是否需要干预

值班用户打开首页时，应该先看到风险、策略状态、执行状态、事件热度和 agent 活跃度，而不是产品介绍性文字和等权重的普通卡片。

**验收标准**

1. 首页顶部必须优先展示“数据链路、策略状态、执行状态、高影响事件”等高价值指标。
2. 顶部说明文案必须改成值班/交易语境，不能继续使用低信息密度的宣传式说明。

### 场景 2：在不影响远端静态部署的前提下简化导航

维护者继续使用现有 `npm run build`、`frontend/dist`、GitHub Actions 和远端静态目录部署，不需要改动远端服务器路径、查询桥接方式或本地后端端口。

**验收标准**

1. 前端构建产物路径仍然是 `frontend/dist`，Vite 构建命令和现有 workflow 保持兼容。
2. 页面移除 `回放` 一级导航，但不强制删除后端 `/api/query/replay`，避免影响已有调试链路。

## 4. 功能需求

- **FR-001**：前端必须移除 `回放` 作为一级导航和前端状态管理项。
- **FR-002**：首页之外的一级导航必须改成 `PM / RT / MEA / Chief` 四个席位页，由每个席位页承担该 agent 的介绍、最新正式产物和适合外部阅读的重点内容。
- **FR-003**：RT 页必须展示战术地图或其公开可读摘要；如果正式 `standing_tactical_map` 尚未物化，也必须用当前只读事实拼出可供阅读的战术板。
- **FR-004**：执行展示必须优先呈现动作、金额、价格、回执状态和原因摘要，不应把交易所订单号作为公开展示重点。
- **FR-005**：首页、各席位页都必须提供明确的空态、旧数据提示或失败提示，而不是直接静默展示空白区域。

## 5. 非功能要求

- **NFR-001**：不得修改远端静态部署的核心约束：`frontend/dist`、`npm run build`、现有 GitHub Actions workflow、`/api/query/*` 路径兼容。
- **NFR-002**：前端改动后必须至少通过 `npm run test` 和 `npm run build`。
- **NFR-003**：UI 文案必须偏交易运营语境，避免“宣传页 / demo / 低信息密度说明”。

## 6. 关键实体

- **Mission Control View**：面向值班用户的四视图前端结构，围绕组合、策略、执行、事件和 agent 状态组织。
- **Agent Showcase Page**：对应 PM / RT / MEA / Chief 的公开阅读页，各自承载岗位介绍、正式产物摘要和对外可读叙事。
- **RT Tactical Board**：Risk Trader 的战术展示层，优先消费正式 `standing_tactical_map`；若当前主链还没有物化资产，则退化为基于 recent execution thoughts、最新执行批次和风控状态的公开摘要。
- **Remote Display Contract**：指当前静态部署依赖的约束集合，包括 `frontend/dist` 构建产物、Vite 构建流程、GitHub Actions 上传与 rsync、以及 query-only API 使用方式。

## 7. 假设与约束

- 远端服务器仍然只消费静态前端产物，不直接部署本地私有控制 runtime。
- 这次 feature 只重构前端读面与文案，不调整控制/agent 提交接口的公开边界。

## 8. 成功标准

- **SC-001**：用户打开首页后，优先看到的是风险和操作信号，而不是介绍性文字和低优先级流水。
- **SC-002**：`回放` 不再作为前端主导航存在，导航复杂度下降。
- **SC-003**：在不修改远端部署链的前提下，前端测试和构建全部通过。
