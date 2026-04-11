# Quickstart：如何使用 002 公共协议

## 1. 后续 feature 的使用原则

- `003-007` 不得重新定义事件信封顶层字段。
- `003-007` 的所有新事件都必须遵守本 feature 的命名规则和交付规则。
- 任一参数 override 都必须能落成 `ParameterChangeRecord` 和参数生效事件。

## 2. 最小接入顺序

1. 选择已有 `event_type` 命名规则。
2. 明确事件应先落 `memory_assets`，再按需做进程内发布或通知。
3. 如果事件对应人工调参或配置注入，补齐参数变更记录。
4. 前端、通知或回放消费时，只消费 `EventEnvelope`，不读取业务模块内部格式。

## 3. 本 feature 的直接消费者

- `003-workflow-control-plane`
- `004-market-intelligence-guards`
- `005-strategy-execution-spine`
- `006-context-agent-gateway`
- `007-state-memory-delivery`
