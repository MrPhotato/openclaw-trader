import type { AssetRecord } from "../types";
import { asRecord, toNumber } from "./misc";
import { trimNumber, usdCompactText } from "./currency";

export const DEFAULT_DISPLAY_EQUITY_USD = 1000;
export const DISPLAY_LEVERAGE = 5;

export type ExposurePill = {
  coin: string;
  direction?: string;
  directionTone?: "long" | "short" | "flat" | "muted";
  exposure: string;
  strategyExposure?: string;
  share: string;
  strategyShare?: string;
};

export function displayEquityBudget(latestPortfolio: Record<string, unknown>): number {
  return toNumber(latestPortfolio["total_equity_usd"]) ?? DEFAULT_DISPLAY_EQUITY_USD;
}

export function displayNominalBudget(latestPortfolio: Record<string, unknown>): number {
  return displayEquityBudget(latestPortfolio) * DISPLAY_LEVERAGE;
}

export function configuredLeverageLabel(latestPortfolio: Record<string, unknown>): string {
  return `${DISPLAY_LEVERAGE}x（名义${usdCompactText(displayNominalBudget(latestPortfolio))}）`;
}

export function nominalMarginPctLabel(value: unknown, latestPortfolio: Record<string, unknown>): string {
  const notional = toNumber(value) ?? 0;
  const nominalBudget = displayNominalBudget(latestPortfolio);
  const pct = nominalBudget > 0 ? (notional / nominalBudget) * 100 : 0;
  return `名义占用 ${pct.toLocaleString("zh-CN", { minimumFractionDigits: pct === 0 ? 0 : 2, maximumFractionDigits: 2 })}%`;
}

export function positionDirectionLabel(
  position?: Record<string, unknown>,
  target?: Record<string, unknown>,
): { label: string; tone: "long" | "short" | "flat" | "muted" } {
  const side = position ? String(position.side ?? "").toLowerCase() : "";
  if (side === "long") {
    return { label: "做多", tone: "long" };
  }
  if (side === "short") {
    return { label: "做空", tone: "short" };
  }
  const targetDirection = target ? String(target.direction ?? "").toLowerCase() : "";
  if (targetDirection === "long") {
    return { label: "待做多", tone: "muted" };
  }
  if (targetDirection === "short") {
    return { label: "待做空", tone: "muted" };
  }
  if (targetDirection === "flat") {
    return { label: "观望", tone: "flat" };
  }
  return { label: "空仓", tone: "muted" };
}

export function positionNotionalLabel(position?: Record<string, unknown>): string {
  if (!position) {
    return "$0";
  }
  const notional = toNumber(position.notional_usd) ?? toNumber(position.current_notional_usd);
  if (notional === null) {
    return "$0";
  }
  return usdCompactText(notional);
}

export function positionNotionalValue(position?: Record<string, unknown>): number {
  if (!position) {
    return 0;
  }
  return toNumber(position.notional_usd) ?? toNumber(position.current_notional_usd) ?? 0;
}

export function targetExposureBandTop(target?: Record<string, unknown>): number | null {
  if (!target) {
    return null;
  }
  const band = Array.isArray(target.target_exposure_band_pct) ? target.target_exposure_band_pct : null;
  if (!band || band.length < 2) {
    return null;
  }
  return toNumber(band[1]);
}

export function targetExposureLabel(target: Record<string, unknown> | undefined, latestPortfolio: Record<string, unknown>): string | undefined {
  const topPct = targetExposureBandTop(target);
  if (topPct === null) {
    return undefined;
  }
  const usd = (displayNominalBudget(latestPortfolio) * topPct) / 100;
  return usdCompactText(usd);
}

export function targetSharePctLabel(target?: Record<string, unknown>): string | undefined {
  const topPct = targetExposureBandTop(target);
  if (topPct === null) {
    return undefined;
  }
  return `${trimNumber(topPct)}%`;
}

export function buildNominalExposurePills(
  latestPortfolio: Record<string, unknown>,
  latestStrategy: Record<string, unknown>,
  supportedCoins?: readonly string[],
): ExposurePill[] {
  const positions = Array.isArray(latestPortfolio["positions"]) ? latestPortfolio["positions"] : [];
  const positionMap = new Map(
    positions
      .map((position) => asRecord(position))
      .filter((position): position is Record<string, unknown> => position !== null)
      .map((position) => [String(position.coin ?? "").toUpperCase(), position]),
  );

  const targets = Array.isArray(latestStrategy["targets"]) ? latestStrategy["targets"] : [];
  const targetMap = new Map(
    targets
      .map((target) => asRecord(target))
      .filter((target): target is Record<string, unknown> => target !== null)
      .map((target) => [String(target.symbol ?? "").toUpperCase(), target]),
  );

  const coins = (supportedCoins && supportedCoins.length > 0
    ? supportedCoins
    : ["BTC", "ETH"]
  ).map((coin) => String(coin).toUpperCase());

  return [
    ...coins.map<ExposurePill>((coin) => {
      const position = positionMap.get(coin);
      const target = targetMap.get(coin);
      const { label: direction, tone } = positionDirectionLabel(position, target);
      return {
        coin,
        direction,
        directionTone: tone,
        exposure: positionNotionalLabel(position),
        strategyExposure: targetExposureLabel(target, latestPortfolio),
        share: nominalMarginPctLabel(positionNotionalValue(position), latestPortfolio),
        strategyShare: targetSharePctLabel(target),
      };
    }),
    {
      coin: "总敞口",
      exposure: usdCompactText(latestPortfolio["total_exposure_usd"]),
      share: nominalMarginPctLabel(latestPortfolio["total_exposure_usd"], latestPortfolio),
    },
  ];
}

export function currentPositionLeverage(asset: AssetRecord, latestPortfolio: Record<string, unknown>): string {
  const positions = Array.isArray(latestPortfolio["positions"]) ? latestPortfolio["positions"] : [];
  const coin = String(asset.payload["coin"] ?? asset.payload["symbol"] ?? "执行记录");
  const match = positions
    .map((position) => asRecord(position))
    .find((position) => String(position?.coin ?? "") === coin);
  if (match?.leverage) {
    return `${match.leverage}x`;
  }
  return "未回传";
}
