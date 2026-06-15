// Pure reducer: fold an SSE wire frame into the accumulated RunState. No side effects,
// no React — this is the primary unit-test target.

import type {
  DepgraphData,
  DevReport,
  ErrorData,
  FileDoneData,
  FileRetryData,
  HelloData,
  PlanData,
  RunState,
  SecurityRejectData,
  StepStartData,
  StepState,
  VerifyData,
  WireFrame,
} from "../types";
import { initialRunState } from "../types";

function upsertStep(
  state: RunState,
  path: string,
  patch: Partial<StepState>,
  base?: Partial<StepState>,
): RunState {
  const existing = state.steps[path];
  const stepOrder = existing ? state.stepOrder : [...state.stepOrder, path];
  const merged: StepState = {
    path,
    action: existing?.action ?? base?.action ?? "modify",
    index: existing?.index ?? base?.index ?? stepOrder.length,
    total: existing?.total ?? base?.total ?? 0,
    status: existing?.status ?? "running",
    attempt: existing?.attempt ?? 0,
    issues: existing?.issues ?? [],
    ...patch,
  };
  return { ...state, steps: { ...state.steps, [path]: merged }, stepOrder };
}

export function applyEvent(prev: RunState, frame: WireFrame): RunState {
  // Cost + sequence bookkeeping applies to every frame.
  let state: RunState = { ...prev, lastSeq: frame.seq };
  if (frame.cost) {
    state.cost = frame.cost;
    const point = frame.cost.cost_usd ?? frame.cost.input_tokens;
    state.costSeries = [...state.costSeries, point];
  }

  switch (frame.type) {
    case "hello": {
      const d = frame.data as unknown as HelloData;
      return {
        ...state,
        runId: d.run_id,
        objective: d.objective,
        lang: d.lang,
        dryRun: d.dry_run,
        status: d.status === "running" ? "running" : state.status,
      };
    }
    case "depgraph": {
      const d = frame.data as unknown as DepgraphData;
      return {
        ...state,
        status: "running",
        stage: "planner",
        graphBuilt: true,
        fileCount: d.files,
        dynamicCount: d.dynamic,
        graph: d.graph ?? state.graph,
      };
    }
    case "plan": {
      const d = frame.data as unknown as PlanData;
      return {
        ...state,
        stage: "coder",
        planSteps: d.steps,
        highRisk: d.high_risk,
      };
    }
    case "step_start": {
      const d = frame.data as unknown as StepStartData;
      return upsertStep(
        { ...state, stage: "coder" },
        d.path,
        { status: "running", index: d.index, total: d.total, action: d.action },
        { index: d.index, total: d.total, action: d.action },
      );
    }
    case "file_retry": {
      const d = frame.data as unknown as FileRetryData;
      return upsertStep(state, d.path, { status: "retry", attempt: d.attempt });
    }
    case "security_reject": {
      const d = frame.data as unknown as SecurityRejectData;
      return upsertStep(state, d.path, {
        status: "security_reject",
        attempt: d.attempt,
        issues: d.issues,
      });
    }
    case "file_done": {
      const d = frame.data as unknown as FileDoneData;
      return upsertStep(state, d.path, { status: d.ok ? "done" : "failed" });
    }
    case "verify": {
      const d = frame.data as unknown as VerifyData;
      return { ...state, stage: "verifier", verify: d };
    }
    case "commit":
      return state;
    case "done": {
      const report = frame.data as unknown as DevReport;
      return {
        ...state,
        status: "done",
        stage: "complete",
        report,
        graph: state.graph,
        cost: report.cost ?? state.cost,
      };
    }
    case "error": {
      const d = frame.data as unknown as ErrorData;
      return { ...state, status: "error", stage: "complete", error: d.message };
    }
    default:
      // Unknown frame type: ignore (forward-compatible), keep cost/seq updates.
      return state;
  }
}

export function reduceFrames(frames: WireFrame[]): RunState {
  return frames.reduce(applyEvent, initialRunState());
}
