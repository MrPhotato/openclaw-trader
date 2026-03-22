import { describe, expect, test } from "vitest";

import { useMissionControlStore } from "../lib/store";

describe("mission control store", () => {
  test("updates view and replay filters", () => {
    useMissionControlStore.setState({
      activeView: "overview",
      connectionState: "closed",
      liveEvents: [],
      replayFilters: { traceId: "", module: "" },
      streamOverview: undefined,
    });
    useMissionControlStore.getState().setView("replay");
    useMissionControlStore.getState().setReplayFilters({ traceId: "trace-1", module: "agent_gateway" });

    expect(useMissionControlStore.getState().activeView).toBe("replay");
    expect(useMissionControlStore.getState().replayFilters).toEqual({
      traceId: "trace-1",
      module: "agent_gateway",
    });
  });
});
