import { useEffect } from "react";

import { eventsUrl } from "../api/client";
import { useRunStore } from "../store/runStore";
import type { WireFrame } from "../types";

const MAX_RECONNECTS = 3;

// Open an EventSource for a run, feed each frame through the pure reducer (via the
// store), close on the terminal done/error frame, and bound reconnection so a dead
// server doesn't spin forever. Each frame is parsed defensively.
export function useRunStream(runId: string | null): void {
  const ingest = useRunStore((s) => s.ingest);
  const reset = useRunStore((s) => s.reset);

  useEffect(() => {
    if (!runId) return;
    reset(runId);

    let es: EventSource | null = null;
    let reconnects = 0;
    let finished = false;

    const close = () => {
      finished = true;
      es?.close();
    };

    const connect = () => {
      es = new EventSource(eventsUrl(runId));
      es.onmessage = (ev: MessageEvent) => {
        try {
          const frame = JSON.parse(ev.data) as WireFrame;
          ingest(frame);
          if (frame.type === "done" || frame.type === "error") close();
        } catch {
          // ignore malformed frame; keep streaming
        }
      };
      es.onerror = () => {
        if (finished) return;
        reconnects += 1;
        if (reconnects > MAX_RECONNECTS) close();
        // else: EventSource auto-reconnects until we close()
      };
    };

    connect();
    return () => {
      finished = true;
      es?.close();
    };
  }, [runId, ingest, reset]);
}
