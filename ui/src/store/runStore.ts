import { create } from "zustand";

import type { RunState, WireFrame } from "../types";
import { initialRunState } from "../types";
import { applyEvent } from "./reducer";

interface RunStore extends RunState {
  ingest: (frame: WireFrame) => void;
  reset: (runId?: string) => void;
}

// High-frequency SSE updates flow through the pure reducer; components subscribe to
// the slices they need (selector subscriptions) so a token tick doesn't re-render the
// whole tree.
export const useRunStore = create<RunStore>((set) => ({
  ...initialRunState(),
  ingest: (frame) => set((state) => applyEvent(state, frame)),
  reset: (runId) => set({ ...initialRunState(), runId: runId ?? null }),
}));
