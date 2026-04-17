import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { RiskThresholdPills } from "../features/overview/RiskThresholdPills";

const baseOverlay = {
  day_peak_equity_usd: "1030",
  current_equity_usd: "1005",
  observe: { drawdown_pct: 1, equity_usd: "1019.7" },
  reduce: { drawdown_pct: 2, equity_usd: "1009.4" },
  exit: { drawdown_pct: 3, equity_usd: "999.1" },
};

describe("RiskThresholdPills", () => {
  test("marks no levels triggered when state is normal", () => {
    render(<RiskThresholdPills riskOverlay={{ state: "normal", ...baseOverlay }} />);
    expect(screen.queryAllByText("已触发")).toHaveLength(0);
  });

  test("marks observe as triggered when state is observe", () => {
    render(<RiskThresholdPills riskOverlay={{ state: "observe", ...baseOverlay }} />);
    expect(screen.getAllByText("已触发")).toHaveLength(1);
  });

  test("marks observe + reduce as triggered when state is reduce", () => {
    render(<RiskThresholdPills riskOverlay={{ state: "reduce", ...baseOverlay }} />);
    expect(screen.getAllByText("已触发")).toHaveLength(2);
  });

  test("marks all three levels triggered when state is exit", () => {
    render(<RiskThresholdPills riskOverlay={{ state: "exit", ...baseOverlay }} />);
    expect(screen.getAllByText("已触发")).toHaveLength(3);
  });

  test("still renders all four labels and values", () => {
    render(<RiskThresholdPills riskOverlay={{ state: "reduce", ...baseOverlay }} />);
    expect(screen.getByText("当日最高")).toBeInTheDocument();
    expect(screen.getByText("观察线")).toBeInTheDocument();
    expect(screen.getByText("回撤线")).toBeInTheDocument();
    expect(screen.getByText("退出线")).toBeInTheDocument();
    expect(screen.getByText("$1,030")).toBeInTheDocument();
    expect(screen.getByText("$1,019.7")).toBeInTheDocument();
    expect(screen.getByText("$1,009.4")).toBeInTheDocument();
    expect(screen.getByText("$999.1")).toBeInTheDocument();
  });
});
