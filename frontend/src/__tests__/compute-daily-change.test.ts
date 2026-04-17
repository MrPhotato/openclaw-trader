import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { computeDailyChange } from "../lib/format";

describe("computeDailyChange", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // Pin "now" to a mid-UTC-day moment so today's date slice is stable.
    vi.setSystemTime(new Date("2026-04-17T12:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  test("returns up when today's equity is above the day's first snapshot", () => {
    const change = computeDailyChange("1050", [
      { created_at: "2026-04-17T00:30:00Z", total_equity_usd: "1000" },
      { created_at: "2026-04-17T06:00:00Z", total_equity_usd: "1030" },
    ]);
    expect(change).not.toBeNull();
    expect(change!.direction).toBe("up");
    expect(change!.pct).toBeCloseTo(5, 4);
  });

  test("returns down when today's equity is below the day's first snapshot", () => {
    const change = computeDailyChange("950", [
      { created_at: "2026-04-17T00:30:00Z", total_equity_usd: "1000" },
    ]);
    expect(change).not.toBeNull();
    expect(change!.direction).toBe("down");
    expect(change!.pct).toBeCloseTo(-5, 4);
  });

  test("returns flat when change is within the noise floor", () => {
    const change = computeDailyChange("1000.001", [
      { created_at: "2026-04-17T00:30:00Z", total_equity_usd: "1000" },
    ]);
    expect(change!.direction).toBe("flat");
  });

  test("falls back to yesterday's last snapshot when today has no data", () => {
    const change = computeDailyChange("1010", [
      { created_at: "2026-04-15T23:00:00Z", total_equity_usd: "990" },
      { created_at: "2026-04-16T23:30:00Z", total_equity_usd: "1000" },
    ]);
    expect(change).not.toBeNull();
    expect(change!.direction).toBe("up");
    expect(change!.pct).toBeCloseTo(1, 4);
  });

  test("returns null when history is empty", () => {
    expect(computeDailyChange("1000", [])).toBeNull();
  });

  test("returns null when current equity is missing or non-positive", () => {
    expect(
      computeDailyChange(null, [
        { created_at: "2026-04-17T00:30:00Z", total_equity_usd: "1000" },
      ]),
    ).toBeNull();
    expect(
      computeDailyChange("0", [
        { created_at: "2026-04-17T00:30:00Z", total_equity_usd: "1000" },
      ]),
    ).toBeNull();
  });
});
