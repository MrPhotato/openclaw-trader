# Quickstart：如何使用 007 交付层

## 1. 状态与记忆

- 状态快照用于“当前系统真相”
- 记忆视图用于 Agent 和复盘
- 回放读模型用于前端和历史查询

## 2. 通知

- 上游模块只提交 `NotificationCommand`
- 通知服务只返回 `NotificationResult`

## 3. 前端

- 前端优先订阅事件流
- 前端查询历史时只读 `ReplayQueryView`
- 不直接读取零散 logs 作为主接口
