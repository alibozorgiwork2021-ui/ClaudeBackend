import { Link, useParams } from "react-router-dom";

import { CounterBar } from "../components/CounterBar";
import { StageTracker } from "../components/StageTracker";
import { StepList } from "../components/StepList";
import { useRunStream } from "../hooks/useRunStream";
import { useRunStore } from "../store/runStore";

export function LivePage() {
  const { id } = useParams<{ id: string }>();
  useRunStream(id ?? null);
  const run = useRunStore();

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-600">{run.objective || "Run"}</h1>
          <p className="text-sm text-muted">
            {run.dryRun ? "dry run · " : ""}
            {run.lang ?? ""} · {run.fileCount} files, {run.dynamicCount} dynamic
            {run.planSteps !== null ? ` · ${run.planSteps} steps (${run.highRisk} high-risk)` : ""}
          </p>
        </div>
        {run.status === "done" && (
          <div className="flex gap-2 text-sm">
            <Link className="text-info hover:underline" to={`/runs/${id}/diff`}>Diff</Link>
            <Link className="text-info hover:underline" to={`/runs/${id}/graph`}>Topology</Link>
            <Link className="text-info hover:underline" to={`/runs/${id}/review`}>Review</Link>
          </div>
        )}
      </div>

      <StageTracker stage={run.stage} error={run.error} />

      {run.error && (
        <div className="bento border-danger/40 p-4 text-sm text-danger">{run.error}</div>
      )}

      <CounterBar cost={run.cost} series={run.costSeries} />

      <div>
        <h2 className="mb-2 text-sm font-500 text-muted">Steps</h2>
        <StepList run={run} />
      </div>

      {run.status === "done" && run.report && (
        <div className="bento p-4 text-sm">
          <span className={run.report.project_ok ? "text-success" : "text-danger"}>
            Project verification {run.report.project_ok ? "PASSED" : "FAILED"}
          </span>
          <span className="text-muted">
            {" "}· created {run.report.created.length}, modified {run.report.modified.length},
            unsafe {run.report.unsafe.length}, review {run.report.review.length}
          </span>
        </div>
      )}
    </div>
  );
}
