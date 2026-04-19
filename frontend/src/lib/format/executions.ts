import type { AssetRecord } from "../types";
import { asRecord, toNumber } from "./misc";
import { priceText, usdText } from "./currency";
import { formatTime } from "./time";

export function actionLabel(value: unknown): string {
  const action = String(value ?? "wait");
  if (action === "open") {
    return "开仓";
  }
  if (action === "add") {
    return "加仓";
  }
  if (action === "reduce") {
    return "减仓";
  }
  if (action === "close") {
    return "平仓";
  }
  if (action === "hold") {
    return "维持仓位";
  }
  return "等待";
}

export function executionRecordTitle(asset: AssetRecord): string {
  return String(asset.payload["coin"] ?? asset.payload["symbol"] ?? "执行记录");
}

export function tradeVerb(asset: AssetRecord): string {
  const side = String(asset.payload["side"] ?? "").toLowerCase();
  const action = String(asset.payload["action"] ?? "").toLowerCase();
  if (action === "reduce" || action === "close") {
    if (side === "long") {
      return "卖出";
    }
    if (side === "short") {
      return "买回";
    }
    return actionLabel(action);
  }
  if (action === "hold") {
    return "持有";
  }
  if (action === "wait") {
    return "观望";
  }
  if (side === "long") {
    return "买入";
  }
  if (side === "short") {
    return "卖空";
  }
  return actionLabel(action);
}

export function tradeHeadline(asset: AssetRecord): string {
  const coin = executionRecordTitle(asset);
  return `${tradeVerb(asset)} ${coin}`;
}

// Backend tags every result row with `success: true` even when nothing
// reached the exchange (the executor's dry-run path returns success=True
// with message="simulated_execution"; reduce/close planners that find no
// position to act on return success=True with message="no_position_to_*").
// Treating those as real trades misleads the user — they show up in the
// "已执行" feed and (before this filter) on the K-line as phantom pins.
// "Real" success requires success=True PLUS a message that means the
// order actually went out: "submitted" from the live broker, or a fill
// recorded in the payload (covers older success rows from before the
// message field was standardised).
export function executionRecordSuccess(asset: AssetRecord): boolean {
  if (asset.payload["success"] !== true) return false;
  const message = String(asset.payload["message"] ?? "").toLowerCase();
  if (message === "simulated_execution") return false;
  if (message.startsWith("no_position_to_")) return false;
  return true;
}

export function executionRecordStatus(asset: AssetRecord): string {
  const message = String(asset.payload["message"] ?? "").toLowerCase();
  if (asset.payload["success"] === true) {
    if (message === "simulated_execution") {
      return "未执行（模拟）";
    }
    if (message.startsWith("no_position_to_")) {
      return "未执行（无仓位）";
    }
    const fills = Array.isArray(asset.payload["fills"]) ? asset.payload["fills"] : [];
    if (fills.length === 0) {
      return "已下单";
    }
    return "已执行";
  }
  if (asset.payload["message"]) {
    return "未成交";
  }
  return "待观察";
}

export function firstFill(asset: AssetRecord): { price: number | null; size: string | null; trade_time: string | null } | null {
  const fills = Array.isArray(asset.payload["fills"]) ? asset.payload["fills"] : [];
  const first = asRecord(fills[0]);
  if (!first) {
    return null;
  }
  return {
    price: toNumber(first.price),
    size: typeof first.size === "string" ? first.size : null,
    trade_time: typeof first.trade_time === "string" ? first.trade_time : null,
  };
}

export function actualFilledNotional(asset: AssetRecord): number | null {
  const fills = Array.isArray(asset.payload["fills"]) ? asset.payload["fills"] : [];
  const total = fills.reduce((sum, fill) => {
    const record = asRecord(fill);
    const price = toNumber(record?.price);
    const size = toNumber(record?.size);
    if (price === null || size === null) {
      return sum;
    }
    return sum + price * size;
  }, 0);
  return total > 0 ? total : null;
}

export function executionRecordSummary(asset: AssetRecord): string {
  const action = actionLabel(asset.payload["action"]);
  const executedNotional = actualFilledNotional(asset);
  const amount = usdText(executedNotional ?? asset.payload["notional_usd"]);
  const price = priceText(asset.payload["fill_price"]);
  const message = typeof asset.payload["message"] === "string" ? asset.payload["message"] : null;
  if (message) {
    return message;
  }
  if (price) {
    return `${action}，成交金额约 ${amount}，成交价 ${price}。`;
  }
  return `${action}，金额约 ${amount}。`;
}

export function executionRecordMeta(asset: AssetRecord): string {
  const fills = Array.isArray(asset.payload["fills"]) ? asset.payload["fills"] : [];
  if (fills.length > 0) {
    return `已回传 ${fills.length} 笔成交回执。`;
  }
  if (asset.payload["technical_failure"] === true) {
    return "这次执行遇到技术问题，系统已记录失败原因。";
  }
  return "这条执行没有额外的公开回执。";
}

export type TradeDirection = "buy" | "sell";

/**
 * Classifies a successful execution as a buy or sell marker for chart
 * overlays.
 *
 *   buy  — opening/adding long,  closing/reducing short  (green, ▲)
 *   sell — opening/adding short, closing/reducing long   (red,   ▼)
 *
 * Returns null for wait/hold/non-trade records so we don't draw markers
 * for no-ops, and null when the record isn't marked successful. A fill
 * entry is NOT required: many records carry `success: true` but the
 * fills payload lands in a separate asset — dropping them here would
 * leave the chart missing trades the feed clearly shows. Callers that
 * need a price (K-line) fall back to the candle close when fill.price
 * is absent.
 *
 * Robust to two ways the backend reports `side` on close/reduce orders:
 *   - the BEFORE-state ("long" / "short") — what the position was
 *   - the AFTER-state ("flat") — what the position became
 * When `side` is "flat" or missing, we infer the trade direction from
 * the fill's exchange side (SELL → was long → "sell" marker; BUY →
 * was short → "buy" marker). Without this fallback, full-close orders
 * (often emitted with side="flat") never get a marker.
 */
export function classifyTradeDirection(asset: AssetRecord): TradeDirection | null {
  if (!executionRecordSuccess(asset)) return null;
  const action = String(asset.payload["action"] ?? "").toLowerCase();
  const side = String(asset.payload["side"] ?? "").toLowerCase();
  if (action === "hold" || action === "wait") return null;
  const closing = action === "reduce" || action === "close";
  if (side === "long") return closing ? "sell" : "buy";
  if (side === "short") return closing ? "buy" : "sell";
  if (closing) {
    const fills = Array.isArray(asset.payload["fills"]) ? asset.payload["fills"] : [];
    const first = asRecord(fills[0]);
    const fillSide = String(first?.side ?? "").toUpperCase();
    if (fillSide === "SELL") return "sell";
    if (fillSide === "BUY") return "buy";
  }
  return null;
}

/** Epoch-ms when the trade actually filled — fill.trade_time > executed_at > created_at. */
export function extractTradeTimeMs(asset: AssetRecord): number | null {
  const fill = firstFill(asset);
  const candidates: unknown[] = [
    fill?.trade_time,
    asset.payload["executed_at"],
    asset.created_at,
  ];
  for (const candidate of candidates) {
    if (typeof candidate === "string" && candidate.length > 0) {
      const ms = new Date(candidate).getTime();
      if (Number.isFinite(ms)) return ms;
    }
  }
  return null;
}

export function tradeTimeLabel(asset: AssetRecord): string {
  const fill = firstFill(asset);
  if (fill?.trade_time) {
    return `下单时间：${formatTime(fill.trade_time)}`;
  }
  if (typeof asset.payload["executed_at"] === "string") {
    return `执行时间：${formatTime(asset.payload["executed_at"])}`;
  }
  return `记录时间：${formatTime(asset.created_at)}`;
}
