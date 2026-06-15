import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewPanel } from "../components/ReviewPanel";
import type { DevReport } from "../types";

function report(overrides: Partial<DevReport> = {}): DevReport {
  return {
    schema_version: 2, ok: true, objective: "o", dry_run: false, branch: "claudebackend/feature-x",
    target_version: "py313", lang: "python", project_ok: true, project_errors: [], project_notes: [],
    created: [], modified: ["a.py"], deleted: [], flagged: [], unsafe: [], review: ["a.py"],
    dynamic: [], security_issues: [], summary: "", verify_steps: {}, graph: null, cost: null,
    security: null, diff: null, ...overrides,
  };
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(async () => ({
    ok: true,
    json: async () => ({ reverted: ["a.py"], kept: [], branch: "claudebackend/feature-x", main_untouched: true }),
  }));
  vi.stubGlobal("fetch", fetchMock);
});

describe("ReviewPanel", () => {
  it("posts a reject decision and shows the git-effect banner", async () => {
    render(<ReviewPanel runId="r" report={report()} />);
    fireEvent.click(screen.getByText("reject"));
    fireEvent.click(screen.getByText("Apply review"));

    await screen.findByText(/Review applied/);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, opts] = fetchMock.mock.calls[0] as [string, { body: string }];
    expect(url).toBe("/api/runs/r/review");
    expect(JSON.parse(opts.body)).toEqual({ decisions: [{ path: "a.py", decision: "reject" }] });
    expect(screen.getByText(/main untouched/)).toBeInTheDocument();
  });

  it("defaults to approve and posts that", async () => {
    render(<ReviewPanel runId="r" report={report()} />);
    fireEvent.click(screen.getByText("Apply review"));
    await screen.findByText(/Review applied/);
    const [, opts] = fetchMock.mock.calls[0] as [string, { body: string }];
    expect(JSON.parse(opts.body)).toEqual({ decisions: [{ path: "a.py", decision: "approve" }] });
  });

  it("states the never-writes-files invariant", () => {
    render(<ReviewPanel runId="r" report={report()} />);
    expect(screen.getByText(/never writes files directly/)).toBeInTheDocument();
  });

  it("shows a dry-run notice instead of controls for a dry run", () => {
    render(<ReviewPanel runId="r" report={report({ dry_run: true })} />);
    expect(screen.getByText(/available for live runs only/)).toBeInTheDocument();
    expect(screen.queryByText("Apply review")).toBeNull();
  });
});
