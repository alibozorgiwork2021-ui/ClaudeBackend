// Thin fetch wrapper over the local serve API. All paths are relative (/api/...): the
// Vite dev server proxies them to 127.0.0.1:8765, and a --ui-dir deployment is same-origin.

import type { DevReport, ReviewDecision, ReviewResult, VisGraph } from "../types";

export interface CreateRunBody {
  path: string;
  objective: string;
  dry_run: boolean;
  lang: string;
  provider?: string;
  model?: string;
  local?: boolean;
  init?: boolean;
  security_gate?: boolean;
}

export interface CreateRunResult {
  id: string;
  status: string;
  dry_run: boolean;
  lang: string;
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = "";
    try {
      detail = ((await res.json()) as { error?: string }).error ?? "";
    } catch {
      detail = res.statusText;
    }
    throw new Error(detail || `request failed (${res.status})`);
  }
  return (await res.json()) as T;
}

export async function createRun(body: CreateRunBody): Promise<CreateRunResult> {
  const res = await fetch("/api/runs", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return json<CreateRunResult>(res);
}

export async function getReport(id: string): Promise<DevReport> {
  return json<DevReport>(await fetch(`/api/runs/${id}/report`));
}

export async function getGraph(id: string): Promise<VisGraph> {
  return json<VisGraph>(await fetch(`/api/runs/${id}/graph`));
}

export async function postReview(
  id: string,
  decisions: ReviewDecision[],
): Promise<ReviewResult> {
  const res = await fetch(`/api/runs/${id}/review`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ decisions }),
  });
  return json<ReviewResult>(res);
}

export function eventsUrl(id: string): string {
  return `/api/runs/${id}/events`;
}
