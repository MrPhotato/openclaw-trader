# 结构化日志、回放与前端

## 1. 目标

前端需要做到三件事：

1. 实时动态展示各模块之间的协作
2. 回放历史流程
3. 支持人工调参与主动触发

这些能力都必须建立在结构化事件之上。

## 2. 每个模块的日志要求

每个模块至少产出三类事件：

- `received`：收到输入或命令
- `produced`：产生输出或决策
- `failed`：失败或降级

建议统一字段：

- `event_id`
- `trace_id`
- `module`
- `entity_type`
- `entity_id`
- `event_type`
- `event_level`
- `occurred_at`
- `payload`
- `human_summary`

## 3. 前端实时展示建议

### 3.1 模块协作泳道

按 10 个模块排列泳道，实时显示：

- 输入事件
- 输出事件
- 状态迁移
- Agent 请求 / 回执
- 下单命令 / 回报

### 3.2 工作流时间线

按 `trace_id` 聚合同一次流程：

- 事实收集
- 风控判断
- 策略刷新
- execution judgment
- 执行
- 通知

### 3.3 参数控制面板

可调整但必须审计的参数示例：

- 量化阈值
- 风控阈值
- 策略调度开关
- Agent 自主性开关
- 通知策略开关

## 4. 回放模型

历史回放至少支持：

- 按 `trace_id` 回放
- 按时间窗口回放
- 按模块过滤
- 按 coin / strategy version 过滤
- 对比某次参数变更前后流程差异

## 5. 当前系统如何过渡

当前系统已经拥有一部分回放素材：

- `dispatch-brief.json/md`
- `strategy-day.json/md`
- position journal
- SQLite `orders` / `risk_checks` / `news_events`
- OpenClaw transcript

未来不应该直接让前端读取这些零散文件，而应：

1. 先把这些输出转为统一事件流
2. 再由回放与前端模块消费事件流生成视图

## 6. 参数治理要求

所有人工调参都必须：

- 走统一入口
- 带 `operator`
- 带 `change reason`
- 带 `scope`
- 带 `effective_at`
- 带回滚引用

调参本身也必须作为结构化事件进入回放流。
