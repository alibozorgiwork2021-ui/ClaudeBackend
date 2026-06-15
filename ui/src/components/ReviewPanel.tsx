import { useMemo, useState } from "react";

import { useRunReview } from "../hooks/useRunReview";
import type { Decision, DevReport, ReviewDecision } from "../types";
import { GitEffectBanner } from "./GitEffectBanner";

export function ReviewPanel({ runId, report }: { runId: string; report: DevReport }) {
  const files = report.review;
  const [choices, setChoices] = useState<Record<string, Decision>>(() =>
    Object.fromEntries(files.map((f) => [f, "approve" as Decision])),
  );
  const { submit, result, error, loading } = useRunReview(runId);

  const decisions: ReviewDecision[] = useMemo(
    () => files.map((path) => ({ path, decision: choices[path] ?? "approve" })),
    [files, choices],
  );

  if (report.dry_run) {
    return (
      <div className="bento p-6 text-sm text-muted">
        Review is available for live runs only. This was a dry run — nothing was written, so there
        is nothing to approve or reject.
      </div>
    );
  }

  if (files.length === 0) {
    return (
      <div className="bento p-6 text-sm text-muted">
        No <span className="num">CLAUDEBACKEND-REVIEW</span> markers — nothing needs human review.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted">
        These files contain <span className="num text-fg">CLAUDEBACKEND-REVIEW</span> markers.
        Approve to keep, or reject to revert the file on the feature branch.
      </p>

      <ul className="bento divide-y divide-border">
        {files.map((path) => (
          <li key={path} className="flex items-center gap-3 px-4 py-3">
            <span className="num min-w-0 flex-1 truncate text-sm">{path}</span>
            {(["approve", "reject"] as Decision[]).map((d) => (
              <button
                key={d}
                onClick={() => setChoices((c) => ({ ...c, [path]: d }))}
                className={`badge cursor-pointer border ${
                  choices[path] === d
                    ? d === "approve"
                      ? "border-success bg-success/15 text-success"
                      : "border-danger bg-danger/15 text-danger"
                    : "border-border text-muted hover:text-fg"
                }`}
              >
                {d}
              </button>
            ))}
          </li>
        ))}
      </ul>

      <div className="flex items-center gap-3">
        <button
          onClick={() => submit(decisions)}
          disabled={loading}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-500 text-white transition-opacity duration-150 hover:opacity-90 disabled:opacity-50 cursor-pointer"
        >
          {loading ? "Applying…" : "Apply review"}
        </button>
        {error && <span className="text-sm text-danger">{error}</span>}
      </div>

      {result && <GitEffectBanner result={result} />}

      <footer className="border-t border-border pt-3 text-xs text-muted">
        This dashboard never writes files directly. It only calls the review endpoint; every effect
        is committed by the server on the isolated feature branch — never on main/master.
      </footer>
    </div>
  );
}
