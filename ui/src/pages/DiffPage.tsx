import { useParams } from "react-router-dom";

import { DiffViewer } from "../components/DiffViewer";
import { useRunReport } from "../hooks/useRunReport";

export function DiffPage() {
  const { id } = useParams<{ id: string }>();
  const { report, error, loading } = useRunReport(id);

  return (
    <div className="flex flex-col gap-3">
      <h1 className="text-lg font-600">Diff</h1>
      {loading && <div className="text-sm text-muted">Loading report…</div>}
      {error && <div className="bento border-danger/40 p-4 text-sm text-danger">{error}</div>}
      {report && <DiffViewer diff={report.diff} unsafe={report.unsafe} />}
    </div>
  );
}
