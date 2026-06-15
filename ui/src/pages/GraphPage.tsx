import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { getGraph } from "../api/client";
import { TopologyGraph } from "../components/TopologyGraph";
import { useRunStore } from "../store/runStore";
import type { VisGraph } from "../types";

export function GraphPage() {
  const { id } = useParams<{ id: string }>();
  const storeGraph = useRunStore((s) => s.graph);
  const storeRunId = useRunStore((s) => s.runId);
  const haveLive = storeRunId === id && storeGraph !== null;
  const [fetched, setFetched] = useState<VisGraph | null>(null);

  useEffect(() => {
    if (!id || haveLive) return;
    let cancelled = false;
    getGraph(id)
      .then((g) => !cancelled && setFetched(g))
      .catch(() => !cancelled && setFetched(null));
    return () => {
      cancelled = true;
    };
  }, [id, haveLive]);

  return (
    <div className="flex flex-col gap-3">
      <h1 className="text-lg font-600">Dependency topology</h1>
      <TopologyGraph graph={haveLive ? storeGraph : fetched} />
    </div>
  );
}
