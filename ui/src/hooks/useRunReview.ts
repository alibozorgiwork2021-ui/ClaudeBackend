import { useState } from "react";

import { postReview } from "../api/client";
import type { ReviewDecision, ReviewResult } from "../types";

export interface ReviewController {
  submit: (decisions: ReviewDecision[]) => Promise<void>;
  result: ReviewResult | null;
  error: string | null;
  loading: boolean;
}

// The UI never writes files itself — it only POSTs decisions to the review endpoint,
// where a reject reverts on the feature branch (never main/master).
export function useRunReview(runId: string | null): ReviewController {
  const [result, setResult] = useState<ReviewResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(decisions: ReviewDecision[]): Promise<void> {
    if (!runId) return;
    setLoading(true);
    setError(null);
    try {
      setResult(await postReview(runId, decisions));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return { submit, result, error, loading };
}
