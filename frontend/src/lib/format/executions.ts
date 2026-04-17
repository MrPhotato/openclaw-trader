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

export function executionRecordSuccess(asset: AssetRecord): boolean {
  return Boolean(asset.payload["success"]);
}

export function executionRecordStatus(asset: AssetRecord): string {
  if (asset.payload["success"] === true) {
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
