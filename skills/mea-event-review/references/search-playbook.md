# 搜索操作手册

## 下 `/gemini` 之前先做一步：市场定价反查

遇到高影响或含糊事件，**优先调 [digital-oracle](../../digital-oracle/SKILL.md) 看市场是否已经把这事定价进去了**。它把 14 个免费金融数据 API（Polymarket / Kalshi 预测市场、CFTC COT 机构持仓、Deribit BTC/ETH 期权 IV 与期限结构、US Treasury 收益率曲线、CME FedWatch 利率概率、CNN Fear & Greed、SEC EDGAR 内部人交易、CoinGecko 等）并发 gather 成一次调用，典型 preset 2 秒内给出多信号对账表。

典型判断顺序：
1. 先问"市场里有没有这事的定价合约"——如果 Polymarket/Kalshi 已经定到 80%+ 概率，说明**新闻是旧闻**，不该标 `high`
2. 再问"方向信号是否一致"——CFTC 机构仓位、期权 IV skew、避险资产相对价，三个独立维度同向才算真正的 regime shift
3. 最后才用 `/gemini` 补"叙事是什么"（文字背景、时间线确认）——它不替你做定价判断，只做背景梳理

这是 harness engineering 的一种：**先让价格给你投票，再去新闻里找故事**，避免"看起来重要但市场不在乎"的假高影响事件。

### 怎么调用：`scripts/digital_oracle_query.py` 包装器

**不要直接 `from digital_oracle import ...`**。用仓库里封装好的 `scripts/digital_oracle_query.py`，它已经处理好 `sys.path`、`gather` 并发、JSON 序列化、provider 失败隔离。

列 preset：
```bash
python3 /Users/chenzian/openclaw-trader/scripts/digital_oracle_query.py --list-presets
```

跑一个 preset（推荐的主要入口）：
```bash
python3 /Users/chenzian/openclaw-trader/scripts/digital_oracle_query.py --preset hormuz_brent_now
```

现成 preset（选和本次事件最相关的一个）：
- `hormuz_brent_now` — Hormuz / Brent 快检（3 信号，~1-2s）。RT 又问 Brent 有效性时用这个
- `oil_geopolitics` — 油价 / 伊朗 / Hormuz / 冲突 / 制裁类（7 信号，~2s）
- `crypto_regime` — BTC/ETH 基差 + 情绪 + 曲线（5 信号）
- `recession_risk` — 宏观数据 surprise 后用（CPI/PCE/NFP/GDP），8 信号含 Fed path
- `stock_crash_risk` — 美股崩盘问题（含 VIX/MOVE 网搜）

**runtime_pack 已经有的信号不要重复抓**：Brent / WTI / DXY / US 10Y / F&G / BTC ETF 活跃度已经在 `payload.macro_prices` 里（走的是后台 15 分钟 cache），preset 里刻意不含 yfinance 历史 —— 需要更丰富的 Yahoo 数据时用 `--signals` 显式点名：

```bash
python3 /Users/chenzian/openclaw-trader/scripts/digital_oracle_query.py \
    --signals spy,gold_price,copper_price,eth_basis
```

列所有可用信号：
```bash
python3 /Users/chenzian/openclaw-trader/scripts/digital_oracle_query.py --list-signals
```

### 输出结构

脚本 stdout 永远是单一 JSON：
```json
{
  "preset": "hormuz_brent_now",
  "elapsed_seconds": 1.73,
  "signal_count": 3,
  "signals": {
    "polymarket_hormuz": {"ok": true, "data": [...]},
    "crude_cot": {"ok": true, "data": [{"report_date": "...", "mm_long": 0, "mm_short": 5460, ...}]},
    "fng": {"ok": true, "data": {"score": 68.1, "rating": "greed", ...}}
  }
}
```

单个 provider 失败**不影响**其他信号，对应 signal 的 `ok=false` + `error=<reason>`。

### 读 JSON 的思路

拿到 JSON 后从三个维度交叉看：

1. **概率维度**（Polymarket / Kalshi）：市场直接定价了多少概率？如果合约价格 > 0.8，事件已经 price in
2. **仓位维度**（CFTC COT）：managed money 净多还是净空？变化方向比绝对值更重要。Long 减、short 加 = 机构在掉头
3. **情绪维度**（F&G / Deribit basis / IV）：对比本周 vs 上周 rating，judgment 是 regime shift 还是延续
4. **时间对齐**：所有信号的定价窗口一致吗？Polymarket 合约可能定 3 个月，CFTC 反映上周三收盘，不能混投票

如果三个维度**一致同向** → 事件确实有影响但方向已被定价，impact 可能不需要 `high`。
如果三个维度**分歧** → 真正的交易机会 / 真正的 regime shift 风险，值得 `high` + `sessions_send`。

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
