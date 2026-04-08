import { create } from "zustand";

import type { EventEnvelope, StreamPayload, ViewKey } from "./types";

type MissionControlState = {
  activeView: ViewKey;
  connectionState: "open" | "closed" | "error";
  liveEvents: EventEnvelope[];
  streamOverview?: StreamPayload["overview"];
  setView: (view: ViewKey) => void;
  setConnectionState: (state: "open" | "closed" | "error") => void;
  setStreamPayload: (payload: StreamPayload) => void;
};

export const useMissionControlStore = create<MissionControlState>((set) => ({
  activeView: "overview",
  connectionState: "closed",
  liveEvents: [],
  streamOverview: undefined,
  setView: (view) => set({ activeView: view }),
  setConnectionState: (state) => set({ connectionState: state }),
  setStreamPayload: (payload) =>
    set({
      streamOverview: payload.overview,
      liveEvents: payload.events,
    }),
}));
