import { useEffect, type RefObject } from "react";
import { type Data, Network } from "vis-network/standalone";

import type { VisGraph } from "../types";

// Render the backend's vis-network payload into a container. The standalone ESM build
// is bundled (no CDN), satisfying the air-gap requirement. Plain node/edge arrays are
// passed directly as vis-network Data (no DataSet needed).
export function useVisNetwork(
  ref: RefObject<HTMLDivElement>,
  graph: VisGraph | null,
): void {
  useEffect(() => {
    if (!ref.current || !graph) return;
    const data: Data = { nodes: graph.nodes, edges: graph.edges };
    const network = new Network(ref.current, data, {
      nodes: { shape: "dot", size: 14, font: { color: "#e7e9ee" } },
      edges: {
        smooth: { enabled: true, type: "continuous", roundness: 0.5 },
        color: { opacity: 0.6 },
      },
      physics: { stabilization: true, barnesHut: { gravitationalConstant: -8000 } },
      interaction: { hover: true, tooltipDelay: 120 },
    });
    return () => network.destroy();
  }, [ref, graph]);
}
