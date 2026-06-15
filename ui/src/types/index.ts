// Mirrors the ClaudeBackend `serve` wire protocol (claudebackend/web/serialize.py)
// and DevReport.to_dict() (orchestrator.py, schema_version 2). Keep in sync.

export type FrameType =
  | "hello"
  | "depgraph"
  | "plan"
  | "step_start"
  | "file_retry"
  | "security_reject"
  | "file_done"
  | "verify"
  | "commit"
  | "done"
  | "error";

export interface Cost {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cost_usd: number | null;
  pricing_known: boolean;
  cache_hit_ratio: number;
  calls: number;
}

// --- vis-network graph payload (claudebackend/core/graphviz.py::_nodes_edges) ---

export interface VisNode {
  id: string;
  label: string;
  title: string;
  group: string;
  color: string;
}

export interface VisEdge {
  from: string;
  to: string;
  arrows: string;
  color: { color: string };
}

export interface VisGraph {
  nodes: VisNode[];
  edges: VisEdge[];
}

// --- DevReport.to_dict() ---

export interface DevReport {
  schema_version: number;
  ok: boolean;
  objective: string;
  dry_run: boolean;
  branch: string | null;
  target_version: string;
  lang: string;
  project_ok: boolean;
  project_errors: string[];
  project_notes: string[];
  created: string[];
  modified: string[];
  deleted: string[];
  flagged: string[];
  unsafe: string[];
  review: string[];
  dynamic: string[];
  security_issues: string[];
  summary: string;
  verify_steps: Record<string, string>;
  graph: string | null;
  cost: Cost | null;
  security: unknown | null;
  diff: string | null;
}

// --- review API ---

export type Decision = "approve" | "reject";

export interface ReviewDecision {
  path: string;
  decision: Decision;
}

export interface ReviewResult {
  reverted: string[];
  kept: string[];
  branch: string;
  main_untouched: boolean;
}

// --- per-event data payloads (dataclasses.asdict on the backend) ---

export interface HelloData {
  run_id: string;
  dry_run: boolean;
  objective: string;
  lang: string;
  status: string;
}
export interface DepgraphData {
  files: number;
  dynamic: number;
  kinds: Record<string, number>;
  graph: VisGraph | null;
}
export interface PlanData {
  steps: number;
  high_risk: number;
}
export interface StepStartData {
  index: number;
  total: number;
  path: string;
  action: string;
}
export interface FileRetryData {
  path: string;
  attempt: number;
}
export interface SecurityRejectData {
  path: string;
  attempt: number;
  issues: string[];
}
export interface FileDoneData {
  path: string;
  ok: boolean;
}
export interface VerifyData {
  steps: Record<string, string>;
  ok: boolean;
}
export interface CommitData {
  paths: string[];
  diff?: string;
}
export interface ErrorData {
  message: string;
}

export interface WireFrame {
  type: FrameType;
  run_id: string;
  seq: number;
  ts: number;
  data: Record<string, unknown>;
  cost: Cost | null;
}

// --- accumulated UI state (output of the pure reducer) ---

export type StageId = "queued" | "planner" | "coder" | "verifier" | "complete";

export type StepStatus =
  | "running"
  | "retry"
  | "security_reject"
  | "done"
  | "failed";

export interface StepState {
  path: string;
  action: string;
  index: number;
  total: number;
  status: StepStatus;
  attempt: number;
  issues: string[];
}

export interface RunState {
  runId: string | null;
  status: "idle" | "running" | "done" | "error";
  objective: string | null;
  lang: string | null;
  dryRun: boolean | null;
  stage: StageId;
  graphBuilt: boolean;
  fileCount: number;
  dynamicCount: number;
  planSteps: number | null;
  highRisk: number | null;
  steps: Record<string, StepState>;
  stepOrder: string[];
  cost: Cost | null;
  costSeries: number[];
  verify: VerifyData | null;
  report: DevReport | null;
  graph: VisGraph | null;
  error: string | null;
  lastSeq: number;
}

export function initialRunState(): RunState {
  return {
    runId: null,
    status: "idle",
    objective: null,
    lang: null,
    dryRun: null,
    stage: "queued",
    graphBuilt: false,
    fileCount: 0,
    dynamicCount: 0,
    planSteps: null,
    highRisk: null,
    steps: {},
    stepOrder: [],
    cost: null,
    costSeries: [],
    verify: null,
    report: null,
    graph: null,
    error: null,
    lastSeq: -1,
  };
}
