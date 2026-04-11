# 模块规格说明：Notification Service

**状态**：主真相层草案  
**对应实现**：`src/openclaw_trader/modules/notification_service/`  
**来源承接**：`001`、`007`

## 1. 背景与目标

`notification_service` 是简单的事件监听与转发模块。它消费 `memory_assets` 中的既定结构化事件，并在需要时响应进程内事件发布，把对应 JSON 序列化成普通文字后直接推送到 owner 与 `Crypto Chief` 的 OpenClaw 对话中，不依赖任何 Agent 思考来决定是否通知或如何通知。

## 2. 职责

- 监听既定结构化事件
- 把结构化 JSON 序列化为普通文字
- 直接推送到 owner-facing 的 OpenClaw 对话
- 维护投递结果和失败原因

## 3. 拥有资产

- `NotificationCommand`
- `NotificationResult`

## 4. 输入

- 来自 `memory_assets` 与进程内事件发布的既定事件
- 第一批只监听：
  - PM 正式策略更新
  - RT 正式下单/执行事件

## 5. 输出

- 已投递或失败的结构化结果
- owner 与 `Crypto Chief` 对话中的普通文字通知

## 6. 直接协作边界

- 从 `memory_assets` / 进程内事件流消费 PM 与 RT 的既定事件
- 向 OpenClaw 消息发送层适配
- 向 `memory_assets` 提交通知结果

## 7. 不负责什么

- 不自行发明通知语义
- 不调用 Agent 做二次思考、改写或总结
- 不把 LLM 文案当正式通知真相
- 不负责复杂模板、分级路由或多渠道编排

## 8. 当前已定

- 通知必须是确定性事件驱动
- 第一批只监听 PM 正式策略更新和 RT 正式下单/执行事件
- `notification_service` 只做 JSON 到普通文字的直接序列化，不经过任何 Agent 思考
- 默认推送到 owner 与 `Crypto Chief` 的 OpenClaw 对话
- 投递结果和失败原因属于正式系统资产

## 9. 待后续讨论

- 多渠道、分级路由和复杂模板是否有必要
