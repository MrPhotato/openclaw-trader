import { create } from "zustand";

import type { EventEnvelope, StreamPayload, ViewKey } from "./types";

type ReplayFilters = {
  traceId: string;
  module: string;
};

type MissionControlState = {
  activeView: ViewKey;
  connectionState: "open" | "closed" | "error";
  liveEvents: EventEnvelope[];
  streamOverview?: StreamPayload["overview"];
  replayFilters: ReplayFilters;
  setView: (view: ViewKey) => void;
  setConnectionState: (state: "open" | "closed" | "error") => void;
  setStreamPayload: (payload: StreamPayload) => void;
  setReplayFilters: (filters: Partial<ReplayFilters>) => void;
};

export const useMissionControlStore = create<MissionControlState>((set) => ({
  activeView: "overview",
  connectionState: "closed",
  liveEvents: [],
  streamOverview: undefined,
  replayFilters: {
    traceId: "",
    module: "",
  },
  setView: (view) => set({ activeView: view }),
  setConnectionState: (state) => set({ connectionState: state }),
  setStreamPayload: (payload) =>
    set({
      streamOverview: payload.overview,
      liveEvents: payload.events,
    }),
  setReplayFilters: (filters) =>
    set((state) => ({
      replayFilters: {
        ...state.replayFilters,
        ...filters,
      },
    })),
}));
