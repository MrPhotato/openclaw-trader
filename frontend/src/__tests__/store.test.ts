import { describe, expect, test } from "vitest";

import { useMissionControlStore } from "../lib/store";

describe("mission control store", () => {
  test("updates active view", () => {
    useMissionControlStore.setState({
      activeView: "overview",
      connectionState: "closed",
      liveEvents: [],
      streamOverview: undefined,
    });
    useMissionControlStore.getState().setView("desk");

    expect(useMissionControlStore.getState().activeView).toBe("desk");
  });
});
