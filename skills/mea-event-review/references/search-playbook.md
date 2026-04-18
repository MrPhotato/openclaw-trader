# 搜索操作手册

## 下 `/gemini` 之前先做一步：市场定价反查

遇到高影响或含糊事件，**优先调 [digital-oracle](../../digital-oracle/SKILL.md) 看市场是否已经把这事定价进去了**。它把 14 个免费金融数据 API（Polymarket / Kalshi 预测市场、CFTC COT 机构持仓、Deribit BTC/ETH 期权 IV 与期限结构、US Treasury 收益率曲线、CME FedWatch 利率概率、CNN Fear & Greed、SEC EDGAR 内部人交易、CoinGecko 等）并发 gather 成一次调用，2 秒内给出多信号对账表。

典型判断顺序：
1. 先问"市场里有没有这事的定价合约"——如果 Polymarket/Kalshi 已经定到 80%+ 概率，说明**新闻是旧闻**，不该标 `high`
2. 再问"方向信号是否一致"——CFTC 机构仓位、期权 IV skew、避险资产相对价，三个独立维度同向才算真正的 regime shift
3. 最后才用 `/gemini` 补"叙事是什么"（文字背景、时间线确认）——它不替你做定价判断，只做背景梳理

这是 harness engineering 的一种：**先让价格给你投票，再去新闻里找故事**，避免"看起来重要但市场不在乎"的假高影响事件。

digital-oracle 著作权归属 [komako-workshop](https://github.com/komako-workshop/digital-oracle)，MIT 许可。

## 何时用 `/gemini`

仅在以下情况使用 `/gemini`：
- 批次内容模糊不清
- 来源可信度不确定
- 事件看起来影响重大**且 digital-oracle 的定价信号不足以解答**（例如主权 CDS、MOVE、TTF 气价等市场不够流动或没有预测合约覆盖的变量）
- 需要交叉来源确认叙事

不要默认对每个条目都使用 `/gemini`。

搜索时，指令必须以下列格式之一开头：
- `Web search for ...`
- `联网搜索：...`

优先搜索目标：
- 弄清发生了什么
- 确认时间线
- 确认影响范围
- 判断事件是否应为 `high`

如果事件为 `high`，直接通知：
- `PM`
- `RT`

## 利好事件同样需要确认
- 如果事件可能显著强化 PM 的 thesis（如关键数据超预期、监管利好、流动性改善信号），同样值得用 `/gemini` 做交叉确认。
- 确认后的利好事件应和利空事件一样及时通知 `PM` 和 `RT`。
- 不要只在"风险"事件上投入搜索精力——漏确认一个利好和漏确认一个利空对团队的损失是对等的。
