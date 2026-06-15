import { GitBranch, ShieldCheck } from "lucide-react";

import type { ReviewResult } from "../types";

export function GitEffectBanner({ result }: { result: ReviewResult }) {
  return (
    <div className="bento flex flex-col gap-2 border-success/40 p-4">
      <div className="flex items-center gap-2 text-sm text-success">
        <ShieldCheck size={16} aria-hidden />
        Review applied
        {result.main_untouched && <span className="text-muted">· main untouched</span>}
      </div>
      <div className="flex items-center gap-2 text-xs text-muted">
        <GitBranch size={14} aria-hidden />
        <span className="num">{result.branch}</span>
      </div>
      {result.reverted.length > 0 && (
        <div className="text-xs">
          <span className="text-danger">reverted:</span>{" "}
          <span className="num text-muted">{result.reverted.join(", ")}</span>
        </div>
      )}
      {result.kept.length > 0 && (
        <div className="text-xs">
          <span className="text-success">kept:</span>{" "}
          <span className="num text-muted">{result.kept.join(", ")}</span>
        </div>
      )}
    </div>
  );
}
