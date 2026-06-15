import parseDiff from "parse-diff";

export interface DiffLine {
  type: "add" | "del" | "normal";
  content: string;
}

export interface DiffFile {
  path: string;
  additions: number;
  deletions: number;
  lines: DiffLine[];
}

// Parse a unified diff string into per-file, render-ready line lists.
export function parseUnifiedDiff(diff: string | null | undefined): DiffFile[] {
  if (!diff) return [];
  const files = parseDiff(diff);
  return files.map((f) => {
    const path = f.to && f.to !== "/dev/null" ? f.to : f.from || "(unknown)";
    const lines: DiffLine[] = [];
    for (const chunk of f.chunks) {
      for (const change of chunk.changes) {
        const type =
          change.type === "add" ? "add" : change.type === "del" ? "del" : "normal";
        lines.push({ type, content: change.content.replace(/^[-+ ]/, "") });
      }
    }
    return {
      path,
      additions: f.additions ?? 0,
      deletions: f.deletions ?? 0,
      lines,
    };
  });
}
