# Quickstart：Macro & Event Analyst

## 场景 1：收到 NEWS_BATCH_READY

1. 被 `workflow_orchestrator` 客观唤醒
2. 阅读新闻批次，必要时自主使用 `/gemini` 扩搜；搜索指令必须以 `Web search for ...` 或 `联网搜索：...` 开头
3. 形成结构化事件列表
4. 通过正式提交通道写入 `memory_assets`

## 场景 2：直接提醒 PM

1. 识别到会影响 thesis、目标仓位、recheck 或 invalidation 的变化
2. 在 OpenClaw 中直接提醒 `PM`
3. 由 `PM` 自己决定是否 revision

## 验收要点

- 正式提交无 `alert`
- 直接沟通不形成系统真相
- 长期记忆只来自 `memory_assets`
