import { useRef } from "react";

import { useVisNetwork } from "../hooks/useVisNetwork";
import type { VisGraph } from "../types";

const LEGEND: { kind: string; label: string; color: string }[] = [
  { kind: "python", label: "Python module", color: "#4f86c6" },
  { kind: "php", label: "PHP module", color: "#777bb3" },
  { kind: "orm", label: "ORM model", color: "#7b5cb8" },
  { kind: "dockerfile", label: "Dockerfile", color: "#2496ed" },
  { kind: "config", label: "Config", color: "#e09f3e" },
];

export function TopologyGraph({ graph }: { graph: VisGraph | null }) {
  const ref = useRef<HTMLDivElement>(null);
  useVisNetwork(ref, graph);

  if (!graph) {
    return <div className="bento p-6 text-sm text-muted">No topology graph for this run yet.</div>;
  }

  const present = new Set(graph.nodes.map((n) => n.group));
  return (
    <div className="relative">
      <div ref={ref} data-testid="vis-network" className="bento h-[70vh] w-full" />
      <div className="bento absolute left-3 top-3 flex flex-col gap-1.5 p-3 text-xs">
        <span className="font-500 text-fg">Topology · {graph.nodes.length} nodes</span>
        {LEGEND.filter((l) => present.has(l.kind)).map((l) => (
          <span key={l.kind} className="flex items-center gap-2 text-muted">
            <span className="h-3 w-3 rounded-sm" style={{ background: l.color }} aria-hidden />
            {l.label}
          </span>
        ))}
      </div>
    </div>
  );
}
