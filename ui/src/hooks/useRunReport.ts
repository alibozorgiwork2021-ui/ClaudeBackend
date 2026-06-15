import { useEffect, useState } from "react";

import { getReport } from "../api/client";
import { useRunStore } from "../store/runStore";
import type { DevReport } from "../types";

// Use the live report from the store when this is the current run; otherwise fetch it
// (deep-link / page-refresh fallback).
export function useRunReport(runId: string | undefined): {
  report: DevReport | null;
  error: string | null;
  loading: boolean;
} {
  const storeReport = useRunStore((s) => s.report);
  const storeRunId = useRunStore((s) => s.runId);
  const [fetched, setFetched] = useState<DevReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const haveLive = storeRunId === runId && storeReport !== null;

  useEffect(() => {
    if (!runId || haveLive) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getReport(runId)
      .then((r) => !cancelled && setFetched(r))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [runId, haveLive]);

  return { report: haveLive ? storeReport : fetched, error, loading };
}
