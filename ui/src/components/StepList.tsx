import type { RunState, StepState, StepStatus } from "../types";

const STATUS: Record<StepStatus, { label: string; cls: string }> = {
  running: { label: "running", cls: "bg-info/15 text-info" },
  retry: { label: "retry", cls: "bg-warn/15 text-warn" },
  security_reject: { label: "security reject", cls: "bg-danger/15 text-danger" },
  done: { label: "done", cls: "bg-success/15 text-success" },
  failed: { label: "failed", cls: "bg-danger/15 text-danger" },
};

function Row({ step }: { step: StepState }) {
  const s = STATUS[step.status];
  return (
    <li className="border-b border-border/60 px-4 py-2.5 last:border-0">
      <div className="flex items-center gap-3">
        <span className="text-xs text-muted">{step.action}</span>
        <span className="num min-w-0 flex-1 truncate text-sm">{step.path}</span>
        {step.attempt > 0 && (
          <span className="num text-xs text-muted">attempt {step.attempt}</span>
        )}
        <span className={`badge ${s.cls}`}>{s.label}</span>
      </div>
      {step.issues.length > 0 && (
        <ul className="mt-1.5 space-y-0.5 pl-1">
          {step.issues.map((issue, i) => (
            <li key={i} className="num text-xs text-danger/90">
              {issue}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

export function StepList({ run }: { run: RunState }) {
  if (run.stepOrder.length === 0) {
    return (
      <div className="bento p-6 text-center text-sm text-muted">
        {run.status === "running" ? "Planning…" : "No steps yet."}
      </div>
    );
  }
  return (
    <ul className="bento divide-border">
      {run.stepOrder.map((path) => (
        <Row key={path} step={run.steps[path]} />
      ))}
    </ul>
  );
}
