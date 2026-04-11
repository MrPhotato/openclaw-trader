# 任务分解：市场智能与风险守卫

**功能分支**：`codex/004-market-intelligence-guards`  
**规格文档**：`specs/004-market-intelligence-guards/spec.md`

## 第一波：范围与职责

- [x] T001 固化数据接入、新闻事件、量化判断和风险守卫四个子域的职责边界，写入 `specs/004-market-intelligence-guards/spec.md`
- [x] T002 固化 `12h/4h/1h` 的当前有效职责分层，写入 `specs/004-market-intelligence-guards/spec.md`

## 第二波：数据模型与契约

- [x] T003 定义市场快照、新闻事件、多时域预测、风险守卫实体，写入 `specs/004-market-intelligence-guards/data-model.md`
- [x] T004 [P] 编写市场快照 schema，写入 `specs/004-market-intelligence-guards/contracts/market-snapshot.schema.json`
- [x] T005 [P] 编写新闻事件 schema，写入 `specs/004-market-intelligence-guards/contracts/news-event.schema.json`
- [x] T006 [P] 编写风险守卫 schema，写入 `specs/004-market-intelligence-guards/contracts/risk-guard-decision.schema.json`
- [x] T007 编写 contracts 索引与下游消费说明，写入 `specs/004-market-intelligence-guards/contracts/README.md`

## 第三波：质量与衔接

- [x] T008 编写实施计划，写入 `specs/004-market-intelligence-guards/plan.md`
- [x] T009 编写 quickstart 与下游使用说明，写入 `specs/004-market-intelligence-guards/quickstart.md`
- [x] T010 编写一致性分析报告，写入 `specs/004-market-intelligence-guards/analysis.md`
- [x] T011 完成 requirements checklist，写入 `specs/004-market-intelligence-guards/checklists/requirements.md`

## 第四波：`policy_risk` 收敛改造

- [x] T012 将 `quant_intelligence` 改为只输出结构化市场事实，不再输出建议型风险许可信号
- [x] T013 将 `1h` 从决策链中移除，不再作为开仓、加仓或风控许可输入
- [x] T014 将 `policy_risk` 收敛为硬风控，只保留交易可用性、硬暴露边界、持仓风险边界三类控制
- [x] T015 将 `event_action`、`portfolio_risk`、`model_uncertainty` 收敛为诊断信息或硬阻断，不再生成复杂软建议
- [x] T016 用新配置层承接上述硬风控参数，并补齐对应单元测试与联调测试
- [x] T017 在 `Trade Gateway.market_data` 增加多尺度价格序列、形态摘要、关键价位、突破/回踩、波动状态、最近订单/成交历史等采集入口
- [ ] T018 第二批再决定上述新增市场上下文字段如何进入 `memory_assets`、`agent_gateway` 运行时输入层和 Agent 视图
