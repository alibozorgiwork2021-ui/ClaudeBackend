import { useParams } from "react-router-dom";

import { ReviewPanel } from "../components/ReviewPanel";
import { useRunReport } from "../hooks/useRunReport";

export function ReviewPage() {
  const { id } = useParams<{ id: string }>();
  const { report, error, loading } = useRunReport(id);

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-3">
      <h1 className="text-lg font-600">Human-in-the-loop review</h1>
      {loading && <div className="text-sm text-muted">Loading report…</div>}
      {error && <div className="bento border-danger/40 p-4 text-sm text-danger">{error}</div>}
      {report && id && <ReviewPanel runId={id} report={report} />}
    </div>
  );
}
