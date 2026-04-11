# 研究记录：RT 当班战术地图

- 当前 RT 的主要问题不是“看不到信息”，而是“每次被叫醒都倾向于重新分析完整世界模型”。
- 已有的 `rt_decision_digest` 解决了“摘要入口”问题，但没有解决“上一轮已形成战术判断如何被持续复用”的问题。
- 真实高自由度交易员的工作方式更接近“维护一份当班 if/then 地图，再对新的触发增量做判断”，而不是每次从零开始。
- 现有架构已经具备适合承接这件事的三个组件：
  - `memory_assets` 负责长期资产
  - `agent_gateway pull/rt` 负责当轮聚合输入
  - `workflow_orchestrator` 负责客观触发，不负责主观战术
- 因此第一版最合理的方向不是改自动入口，而是新增：
  - `standing_tactical_map`
  - `trigger_delta`
- 同时保留 drill-down 原始上下文，避免把 RT 变成机械执行器。
