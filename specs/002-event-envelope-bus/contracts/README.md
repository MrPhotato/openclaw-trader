# Contracts

本目录定义 `002-event-envelope-bus` 的公共协议契约。

- `event-envelope.schema.json`：统一事件信封 schema
- `event-routing.md`：基础事件类型与交付规则
- `parameter-change.schema.json`：参数变更与生效事件 schema

后续 `003-007` 只能复用或增量扩展这些契约，不得重定义另一套顶层协议。
