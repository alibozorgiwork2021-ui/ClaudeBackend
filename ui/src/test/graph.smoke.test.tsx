import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// vis-network needs a real canvas; mock it so the component mounts in jsdom.
vi.mock("vis-network/standalone", () => ({
  Network: vi.fn().mockImplementation(() => ({ destroy: vi.fn() })),
}));
vi.mock("vis-data", () => ({
  DataSet: vi.fn().mockImplementation((data: unknown) => data),
}));

import { TopologyGraph } from "../components/TopologyGraph";
import type { VisGraph } from "../types";

const GRAPH: VisGraph = {
  nodes: [{ id: "a.py", label: "a.py", title: "a.py", group: "python", color: "#4f86c6" }],
  edges: [],
};

describe("TopologyGraph", () => {
  it("renders the container and legend for present kinds", () => {
    render(<TopologyGraph graph={GRAPH} />);
    expect(screen.getByTestId("vis-network")).toBeInTheDocument();
    expect(screen.getByText(/1 nodes/)).toBeInTheDocument();
    expect(screen.getByText("Python module")).toBeInTheDocument();
  });

  it("shows an empty state when there is no graph", () => {
    render(<TopologyGraph graph={null} />);
    expect(screen.getByText(/No topology graph/)).toBeInTheDocument();
  });
});
