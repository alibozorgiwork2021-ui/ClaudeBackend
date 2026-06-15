import { describe, expect, it } from "vitest";

import { applyEvent, reduceFrames } from "../store/reducer";
import { initialRunState, type Cost, type WireFrame } from "../types";

function f(type: WireFrame["type"], data: Record<string, unknown>, cost: Cost | null = null, seq = 0): WireFrame {
  return { type, run_id: "r", seq, ts: 0, data, cost };
}

const COST: Cost = {
  input_tokens: 1000,
  output_tokens: 200,
  cache_read_tokens: 0,
  cache_write_tokens: 0,
  cost_usd: 0.5,
  pricing_known: true,
  cache_hit_ratio: 0,
  calls: 1,
};

describe("reducer", () => {
  it("hello sets run metadata and running status", () => {
    const s = applyEvent(initialRunState(), f("hello", {
      run_id: "r1", dry_run: true, objective: "do x", lang: "php", status: "running",
    }));
    expect(s.objective).toBe("do x");
    expect(s.lang).toBe("php");
    expect(s.dryRun).toBe(true);
    expect(s.status).toBe("running");
  });

  it("advances stage planner -> coder -> verifier -> complete", () => {
    let s = initialRunState();
    s = applyEvent(s, f("depgraph", { files: 3, dynamic: 0, kinds: { python: 3 }, graph: { nodes: [], edges: [] } }));
    expect(s.stage).toBe("planner");
    expect(s.graphBuilt).toBe(true);
    expect(s.graph).toEqual({ nodes: [], edges: [] });
    s = applyEvent(s, f("plan", { steps: 2, high_risk: 1 }));
    expect(s.stage).toBe("coder");
    expect(s.planSteps).toBe(2);
    s = applyEvent(s, f("verify", { steps: { compile: "ok" }, ok: true }));
    expect(s.stage).toBe("verifier");
    expect(s.verify?.ok).toBe(true);
  });

  it("tracks per-step status transitions", () => {
    let s = initialRunState();
    s = applyEvent(s, f("step_start", { index: 1, total: 1, path: "a.py", action: "modify" }));
    expect(s.steps["a.py"].status).toBe("running");
    expect(s.stepOrder).toEqual(["a.py"]);
    s = applyEvent(s, f("file_retry", { path: "a.py", attempt: 1 }));
    expect(s.steps["a.py"].status).toBe("retry");
    expect(s.steps["a.py"].attempt).toBe(1);
    s = applyEvent(s, f("security_reject", { path: "a.py", attempt: 2, issues: ["[high] SQLi"] }));
    expect(s.steps["a.py"].status).toBe("security_reject");
    expect(s.steps["a.py"].issues).toEqual(["[high] SQLi"]);
    s = applyEvent(s, f("file_done", { path: "a.py", ok: true }));
    expect(s.steps["a.py"].status).toBe("done");
  });

  it("file_done ok=false marks the step failed", () => {
    let s = applyEvent(initialRunState(), f("step_start", { index: 1, total: 1, path: "b.py", action: "create" }));
    s = applyEvent(s, f("file_done", { path: "b.py", ok: false }));
    expect(s.steps["b.py"].status).toBe("failed");
  });

  it("accumulates a cost series and tracks the latest cost", () => {
    let s = initialRunState();
    s = applyEvent(s, f("step_start", { index: 1, total: 1, path: "a.py", action: "modify" }, COST, 0));
    s = applyEvent(s, f("file_done", { path: "a.py", ok: true }, { ...COST, cost_usd: 0.9 }, 1));
    expect(s.costSeries).toEqual([0.5, 0.9]);
    expect(s.cost?.cost_usd).toBe(0.9);
  });

  it("done hydrates the report and completes", () => {
    const report = {
      schema_version: 2, ok: true, objective: "o", dry_run: true, branch: null,
      target_version: "py313", lang: "python", project_ok: true, project_errors: [],
      project_notes: [], created: [], modified: ["a.py"], deleted: [], flagged: [],
      unsafe: [], review: [], dynamic: [], security_issues: [], summary: "",
      verify_steps: {}, graph: null, cost: { ...COST, cost_usd: 1.2 }, security: null, diff: "x",
    };
    const s = applyEvent(initialRunState(), f("done", report as unknown as Record<string, unknown>));
    expect(s.status).toBe("done");
    expect(s.stage).toBe("complete");
    expect(s.report?.modified).toEqual(["a.py"]);
    expect(s.cost?.cost_usd).toBe(1.2);
  });

  it("error sets error status and message", () => {
    const s = applyEvent(initialRunState(), f("error", { message: "boom" }));
    expect(s.status).toBe("error");
    expect(s.error).toBe("boom");
  });

  it("ignores an unknown frame type but keeps seq bookkeeping", () => {
    const s = applyEvent(initialRunState(), f("totally_new" as WireFrame["type"], { x: 1 }, null, 7));
    expect(s.status).toBe("idle");
    expect(s.lastSeq).toBe(7);
  });

  it("reduceFrames folds a full run", () => {
    const s = reduceFrames([
      f("hello", { run_id: "r", dry_run: true, objective: "o", lang: "python", status: "running" }),
      f("depgraph", { files: 1, dynamic: 0, kinds: { python: 1 }, graph: { nodes: [], edges: [] } }),
      f("plan", { steps: 1, high_risk: 0 }),
      f("step_start", { index: 1, total: 1, path: "a.py", action: "modify" }),
      f("file_done", { path: "a.py", ok: true }),
      f("verify", { steps: { compile: "ok" }, ok: true }),
    ]);
    expect(s.stage).toBe("verifier");
    expect(s.steps["a.py"].status).toBe("done");
  });
});
