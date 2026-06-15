import { renderHook } from "@testing-library/react";
import { act } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useRunStream } from "../hooks/useRunStream";
import { useRunStore } from "../store/runStore";
import { initialRunState } from "../types";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  closed = false;
  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }
  emit(obj: unknown) {
    this.onmessage?.({ data: JSON.stringify(obj) });
  }
  fail() {
    this.onerror?.({});
  }
  close() {
    this.closed = true;
  }
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource as unknown as typeof EventSource);
  useRunStore.setState(initialRunState());
});

describe("useRunStream", () => {
  it("feeds frames into the store", () => {
    renderHook(() => useRunStream("r1"));
    const es = FakeEventSource.instances.at(-1)!;
    act(() => {
      es.emit({ type: "hello", run_id: "r1", seq: -1, ts: 0, data: { run_id: "r1", dry_run: true, objective: "o", lang: "python", status: "running" }, cost: null });
      es.emit({ type: "plan", run_id: "r1", seq: 1, ts: 0, data: { steps: 3, high_risk: 1 }, cost: null });
    });
    expect(useRunStore.getState().planSteps).toBe(3);
    expect(useRunStore.getState().status).toBe("running");
  });

  it("closes the stream on a done frame", () => {
    renderHook(() => useRunStream("r1"));
    const es = FakeEventSource.instances.at(-1)!;
    act(() => {
      es.emit({ type: "done", run_id: "r1", seq: 5, ts: 0, data: { schema_version: 2, modified: [] }, cost: null });
    });
    expect(es.closed).toBe(true);
    expect(useRunStore.getState().status).toBe("done");
  });

  it("stops reconnecting after the bounded retry budget", () => {
    renderHook(() => useRunStream("r1"));
    const es = FakeEventSource.instances.at(-1)!;
    act(() => {
      es.fail();
      es.fail();
      es.fail();
      expect(es.closed).toBe(false); // within budget, EventSource auto-reconnects
      es.fail();
    });
    expect(es.closed).toBe(true); // budget exhausted -> closed
  });

  it("ignores a malformed frame without throwing", () => {
    renderHook(() => useRunStream("r1"));
    const es = FakeEventSource.instances.at(-1)!;
    act(() => {
      es.onmessage?.({ data: "not json{" });
    });
    expect(useRunStore.getState().status).toBe("idle");
  });
});
