import type { AssetRecord } from "../../lib/types";
import {
  actualFilledNotional,
  currentPositionLeverage,
  executionRecordMeta,
  executionRecordStatus,
  executionRecordSuccess,
  firstFill,
  toNumber,
  tradeHeadline,
  tradeTimeLabel,
  tradeVerb,
  trimNumber,
  usdText,
} from "../../lib/format";

export function TradeBlotterCard(props: { asset: AssetRecord; latestPortfolio: Record<string, unknown> }) {
  const fill = firstFill(props.asset);
  const leverage = currentPositionLeverage(props.asset, props.latestPortfolio);
  const executedNotional = actualFilledNotional(props.asset);
  const plannedNotional = toNumber(props.asset.payload["notional_usd"]);
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4 ring-hairline hover-lift">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium">{tradeHeadline(props.asset)}</div>
          <div className="mt-1 text-xs text-slate-400">{tradeTimeLabel(props.asset)}</div>
        </div>
        <div className={executionRecordSuccess(props.asset) ? "text-neon" : "text-red-300"}>{executionRecordStatus(props.asset)}</div>
      </div>
      <div className="mt-3 grid gap-2 text-sm tabular-nums text-slate-300 sm:grid-cols-2">
        <div>交易方向：{tradeVerb(props.asset)}</div>
        <div>成交金额：{executedNotional !== null ? usdText(executedNotional) : usdText(props.asset.payload["notional_usd"])}</div>
        <div>成交价：{fill?.price ? `$${trimNumber(fill.price)}` : "未回传"}</div>
        <div>成交数量：{fill?.size ?? "未回传"}</div>
        <div>当前杠杆：{leverage}</div>
      </div>
      {executedNotional !== null && plannedNotional !== null && Math.abs(executedNotional - plannedNotional) > 0.01 ? (
        <div className="mt-2 text-xs text-slate-400 tabular-nums">计划金额：{usdText(plannedNotional)}</div>
      ) : null}
      <div className="mt-2 text-xs text-slate-500">{executionRecordMeta(props.asset)}</div>
    </div>
  );
}
