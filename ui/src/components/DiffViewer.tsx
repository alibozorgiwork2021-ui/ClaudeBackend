import { FileWarning } from "lucide-react";
import { useMemo, useState } from "react";

import { parseUnifiedDiff } from "../lib/diff";

const LINE_CLS: Record<string, string> = {
  add: "bg-success/10 text-success",
  del: "bg-danger/10 text-danger",
  normal: "text-muted",
};

export function DiffViewer({ diff, unsafe }: { diff: string | null; unsafe: string[] }) {
  const files = useMemo(() => parseUnifiedDiff(diff), [diff]);
  const [selected, setSelected] = useState(0);

  if (files.length === 0 && unsafe.length === 0) {
    return <div className="bento p-6 text-sm text-muted">No diff available (live runs commit per file; this view is for dry-run previews).</div>;
  }

  const file = files[selected];
  return (
    <div className="grid grid-cols-[minmax(180px,260px)_1fr] gap-3">
      <ul className="bento max-h-[72vh] overflow-auto p-1.5">
        {files.map((f, i) => (
          <li key={f.path}>
            <button
              onClick={() => setSelected(i)}
              className={`flex w-full items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-left text-xs cursor-pointer ${
                i === selected ? "bg-surface-2 text-fg" : "text-muted hover:bg-surface-2"
              }`}
            >
              <span className="num min-w-0 truncate">{f.path}</span>
              <span className="num shrink-0">
                <span className="text-success">+{f.additions}</span>{" "}
                <span className="text-danger">-{f.deletions}</span>
              </span>
            </button>
          </li>
        ))}
        {unsafe.map((p) => (
          <li
            key={p}
            className="flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs text-danger"
            title="blocked by the security gate — not written"
          >
            <FileWarning size={14} aria-hidden />
            <span className="num min-w-0 truncate">{p}</span>
          </li>
        ))}
      </ul>

      <div className="bento overflow-auto p-0">
        {file ? (
          <pre className="num m-0 max-h-[72vh] overflow-auto p-0 text-xs leading-relaxed">
            {file.lines.map((ln, i) => (
              <div key={i} className={`px-3 ${LINE_CLS[ln.type]}`}>
                <span className="select-none pr-2 opacity-50">
                  {ln.type === "add" ? "+" : ln.type === "del" ? "-" : " "}
                </span>
                {ln.content || " "}
              </div>
            ))}
          </pre>
        ) : (
          <div className="p-6 text-sm text-danger">
            Files listed in red were blocked by the security gate and never written.
          </div>
        )}
      </div>
    </div>
  );
}
