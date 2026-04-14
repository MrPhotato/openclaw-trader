# 正式输出

提交前，打开并严格遵循以下 schema：
- `specs/modules/agent_gateway/contracts/news.schema.json`

Prompt 合约参考：
- `specs/modules/agent_gateway/contracts/news.prompt.md`

## Schema 字段

每个 `events[]` 条目必需：
- `event_id` — 事件唯一标识。**同一事件复发请复用相同的 event_id**，系统按 event_id 去重（相同 id 会覆盖旧条目）。
- `category` — 事件分类（如 `"monetary_policy"`, `"geopolitical"`, `"regulatory"`, `"market_structure"` 等）。
- `summary` — 1-2 句话的事件摘要。
- `impact_level` — `"low"` / `"medium"` / `"high"`。

可选字段：
- `thesis_alignment` — 事件与 PM 当前策略 thesis 的关系。四个合法值 + null：
  - `"reinforces"` — 强化 thesis（PM 可考虑扩大敞口）。
  - `"weakens"` — 削弱 thesis（PM 可考虑缩减）。
  - `"flip_trigger"` — 命中 PM 明文列出的 flip 阈值（**紧急复盘**）。
  - `"neutral"` — 信息性的，无方向含义。
  - 省略或 `null` — 事件与任何活跃策略无关，不做判断。
- 用法：在 `latest_strategy.flip_triggers` 里找到匹配阈值 → 标 `"flip_trigger"`；与 `portfolio_thesis` 方向一致的强利好 → `"reinforces"`；与 `portfolio_invalidation` 条件接近 → `"weakens"`。

## 规则
- 正式提交必须是恰好一个 JSON 对象。
- 保留运行时包中的 `input_id`，并在调用 submit bridge 时一并发送。
- 仅输出 JSON。不得输出 markdown 围栏、散文、旁注或尾部说明。
- 仅提交结构化事件列表。不要添加 `submission_id` 或 `generated_at_utc`；系统会自动生成。
- 每条事件摘要应保持简洁。
- 不要输出 `alert` 字段。
- 对 `PM` 和 `RT` 的直接提醒属于对话行为，不是正式提交字段。

## 示例

```json
{
  "events": [
    {
      "event_id": "wti_breach_2026_04_14",
      "category": "energy",
      "summary": "WTI 1h 收盘突破 105 美元，Chief Rev289 空头触发线被激活。",
      "impact_level": "high",
      "thesis_alignment": "flip_trigger"
    },
    {
      "event_id": "fomc_minutes_2026_04",
      "category": "monetary_policy",
      "summary": "FOMC 会议纪要偏鸽，委员支持年内提前降息。",
      "impact_level": "medium",
      "thesis_alignment": "reinforces"
    },
    {
      "event_id": "imf_weo_april_2026",
      "category": "macro_data",
      "summary": "IMF 将全球增长预期下调至 3.3%，亚洲最弱。",
      "impact_level": "low"
    }
  ]
}
```
