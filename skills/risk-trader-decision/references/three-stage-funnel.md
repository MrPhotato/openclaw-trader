# 三阶段漏斗

# 默认读取顺序
在进入漏斗前，按以下顺序读取：
- `trigger_delta`
- `standing_tactical_map`
- `rt_decision_digest`
- helper 生成的 `/tmp/rt_execution_submission.json`

仅在摘要留有歧义时才深入查看原始区段：
- `execution_contexts`
- `market.market_context`
- `recent_execution_thoughts`
- `news_events`

## 1. 任务资格判断
首先读取：
- `trigger_delta`
- `standing_tactical_map`
- `rt_decision_digest.trigger_summary`
- `rt_decision_digest.portfolio_summary`
- `rt_decision_digest.strategy_summary`
- 当前目标和目标缺口
- `target_exposure_band_pct`
- `rt_discretion_band_pct`
- `policy_risk`
- 当前持仓和账户状态

回答：
- 我现在能否操作
- 我现在是否需要操作
- 本轮是否需要同时刷新战术地图
- 提交脚手架的哪些部分需要填写而非重建
- 如果 PM 有活跃的未锁定入场缺口，我是现在入场还是通过 `pm_recheck_requested` 明确升级
- 如果 PM 方向是对的且我已经有仓位，当前仓位够不够让团队赚到钱？有没有 add 的空间和理由？

## 2. 市场时机判断
其次读取：
- `rt_decision_digest.focus_symbols`
- `QI` `1h/4h/12h`
- 压缩价格序列
- 关键价位
- 突破/回测状态
- 波动率状态
- 形态摘要

回答：
- 现在是否适合操作
- 应该追、等、减，还是只部分执行
- 如果趋势在走且我的仓位远低于 band 上限，"不追"是不是变成了"不赚"？

## 3. 执行落地
最后读取：
- `rt_decision_digest.recent_memory`
- 最优买卖价
- 价差
- 深度
- 挂单
- 近期成交和失败记录
- 产品约束

回答：
- 现在如何操作
- 本批次处理多少个币种
- 应该 `open / add / reduce / close / wait`
