import { toNumber } from "./misc";

export function trimNumber(value: number): string {
  return value.toLocaleString("zh-CN", {
    maximumFractionDigits: value >= 100 ? 2 : 4,
  });
}

export function usdText(value: unknown): string {
  const number = toNumber(value);
  if (number === null) {
    return "0 美元";
  }
  return `${trimNumber(number)} 美元`;
}

export function usdCompactText(value: unknown): string {
  const number = toNumber(value);
  if (number === null) {
    return "--";
  }
  return `$${trimNumber(number)}`;
}

export function priceText(value: unknown): string | null {
  const number = toNumber(value);
  if (number === null) {
    return null;
  }
  return `$${trimNumber(number)}`;
}

export function formatPct(value: unknown): string {
  const number = toNumber(value);
  if (number === null) {
    return "0%";
  }
  return `${trimNumber(number)}%`;
}

export function formatBandValue(value: unknown): string {
  const number = toNumber(value);
  return number === null ? "0%" : `${trimNumber(number)}%`;
}
