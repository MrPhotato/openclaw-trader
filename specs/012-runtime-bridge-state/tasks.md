# 任务分解：Runtime Bridge State

**功能分支**：`codex/011-rt-tactical-map`  
**规格文档**：`specs/012-runtime-bridge-state/spec.md`

## 第一波：规格与契约收口

- [X] T001 完成 `specs/012-runtime-bridge-state/spec.md`、`plan.md`、`research.md`、`data-model.md`、`quickstart.md`
- [X] T002 定义 `runtime_bridge_state` 最小数据形状和回退语义

## 第二波：主真相层与后台刷新器

- [X] T003 在 `state_memory` 中增加 `RuntimeBridgeState` 模型与读写入口
- [X] T004 新增后台 `RuntimeBridgeMonitor`，持续刷新聚合状态
- [X] T005 为运行配置增加聚合层开关、刷新间隔和允许年龄

## 第三波：agent_gateway 热路径接入

- [X] T006 让 `pull/*` 优先读取 `runtime_bridge_state`
- [X] T007 在 `pull/*` 中保留动态字段补丁与 direct fallback
- [X] T008 暴露本次 pack 的快照来源与新鲜度信息

## 第四波：验证与实验

- [X] T009 补充 `tests.test_v2_agent_gateway` 与相关测试，覆盖缓存命中和回退逻辑
- [X] T010 重启本地 API 宿主并做一次真实 RT 实验
- [X] T011 基于实验结果收口并更新任务状态
