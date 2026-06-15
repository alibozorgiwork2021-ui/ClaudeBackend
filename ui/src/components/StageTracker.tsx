import { Check } from "lucide-react";

import type { StageId } from "../types";

const STAGES: { id: StageId; label: string }[] = [
  { id: "planner", label: "Planner" },
  { id: "coder", label: "Coder" },
  { id: "verifier", label: "Verifier" },
];

const ORDER: StageId[] = ["queued", "planner", "coder", "verifier", "complete"];

export function StageTracker({ stage, error }: { stage: StageId; error?: string | null }) {
  const current = ORDER.indexOf(stage);
  return (
    <div className="bento flex items-center gap-2 p-4">
      {STAGES.map((s, i) => {
        const idx = ORDER.indexOf(s.id);
        const done = current > idx;
        const active = stage === s.id;
        const failed = !!error && active;
        return (
          <div key={s.id} className="flex flex-1 items-center gap-2">
            <div
              className={`flex h-8 w-8 items-center justify-center rounded-full border text-xs transition-colors duration-200 ${
                failed
                  ? "border-danger bg-danger/20 text-danger"
                  : done
                    ? "border-success bg-success/20 text-success"
                    : active
                      ? "border-primary bg-primary/20 text-fg"
                      : "border-border text-muted"
              }`}
            >
              {done ? <Check size={16} aria-hidden /> : i + 1}
            </div>
            <span className={active ? "text-fg" : done ? "text-success" : "text-muted"}>
              {s.label}
            </span>
            {i < STAGES.length - 1 && (
              <div className={`mx-1 h-px flex-1 ${done ? "bg-success" : "bg-border"}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}
