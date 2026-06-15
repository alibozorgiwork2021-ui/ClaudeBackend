"""In-memory run registry + the worker that bridges the synchronous, blocking
``develop_feature`` pipeline (run on a daemon thread) onto the server's asyncio event
loop.

The pipeline calls ``on_event`` from the worker thread; each event becomes a wire
frame appended to ``handle.frames`` (the single ordered source the SSE drain replays
and late-joiners catch up from) and signals the loop via ``call_soon_threadsafe`` so a
connected stream wakes immediately. No outbound network of any kind — only the
user-selected LLM client makes calls, and ``local=True`` forces local Ollama.
"""

from __future__ import annotations

import threading
import time
import uuid

from claudebackend.core import events, git
from claudebackend.web import serialize


class RunHandle:
    """State for one development run. All mutation of ``frames``/``status`` happens
    on the worker thread; the loop only reads them (GIL-safe for these ops)."""

    def __init__(self, run_id, root, *, objective, dry_run, lang):
        self.id = run_id
        self.root = root
        self.objective = objective
        self.dry_run = dry_run
        self.lang = lang
        self.status = "running"  # running | done | error
        self.frames: list[dict] = []
        self.graph: dict | None = None
        self.report: dict | None = None
        self.error: str | None = None
        self.baseline_sha: str | None = None
        self.client = None
        self.loop = None       # set by the POST handler (the running event loop)
        self.tick = None       # asyncio.Event, set on every new frame
        self._seq = 0

    def next_seq(self) -> int:
        s = self._seq
        self._seq += 1
        return s

    def emit(self, frame: dict) -> None:
        """Append a frame (the replayable source of truth) and best-effort wake any
        connected SSE stream. Signalling failures (e.g. a closed loop) are ignored —
        the frame is still buffered for replay."""
        self.frames.append(frame)
        loop, tick = self.loop, self.tick
        if loop is not None and tick is not None:
            try:
                loop.call_soon_threadsafe(tick.set)
            except RuntimeError:  # loop already closed
                pass

    def summary(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "objective": self.objective,
            "dry_run": self.dry_run,
            "lang": self.lang,
            "frames": len(self.frames),
            "error": self.error,
        }


class RunRegistry:
    def __init__(self):
        self._runs: dict[str, RunHandle] = {}

    def create(self, root, *, objective, dry_run, lang) -> RunHandle:
        run_id = uuid.uuid4().hex[:12]
        handle = RunHandle(run_id, root, objective=objective, dry_run=dry_run, lang=lang)
        self._runs[run_id] = handle
        return handle

    def get(self, run_id) -> RunHandle | None:
        return self._runs.get(run_id)

    def list(self) -> list[dict]:
        return [h.summary() for h in self._runs.values()]

    def has_active_run(self, root) -> bool:
        """True if a non-dry run for ``root`` is still in progress (used to refuse a
        second concurrent live run on the same repo, which would race git)."""
        import os

        target = os.path.abspath(str(root))
        return any(
            h.status == "running" and not h.dry_run
            and os.path.abspath(str(h.root)) == target
            for h in self._runs.values()
        )


def run_pipeline_thread(handle: RunHandle, client, develop_kwargs: dict) -> None:
    """Daemon-thread target: run the pipeline, streaming frames onto the handle."""
    from claudebackend.orchestrator import develop_feature

    handle.client = client
    kwargs = dict(develop_kwargs)

    def on_event(event) -> None:
        fr = serialize.event_frame(
            event, run_id=handle.id, seq=handle.next_seq(), ts=time.time(),
            cost=serialize.cost_snapshot(client),
        )
        if isinstance(event, events.DepGraphDone) and event.graph:
            handle.graph = event.graph
        # Live runs stream the real per-commit diff as each commit lands.
        if isinstance(event, events.Commit) and not handle.dry_run:
            try:
                fr["data"]["diff"] = git.show_commit_diff(handle.root, event.paths)
            except git.GitError:  # diff is best-effort, never fatal
                pass
        handle.emit(fr)

    try:
        # Live run: prepare the repo and capture a revert baseline BEFORE any change,
        # so a later review-reject can restore files — even for an init-on-non-repo
        # run (where the baseline commit only exists after we create it here).
        if not handle.dry_run:
            if not git.is_repo(handle.root) and kwargs.get("init"):
                git.init_baseline(handle.root)
            if git.is_repo(handle.root):
                try:
                    handle.baseline_sha = git.head_sha(handle.root)
                except git.GitError:
                    handle.baseline_sha = None
                kwargs["init"] = False  # repo is ready; don't re-init inside the pipeline

        report = develop_feature(
            handle.root, client=client, objective=handle.objective,
            on_event=on_event, dry_run=handle.dry_run, lang=handle.lang,
            assume_yes=True, **kwargs,
        )
        handle.report = report.to_dict()
        handle.status = "done"
        handle.emit(serialize.frame(
            "done", handle.report, run_id=handle.id, seq=handle.next_seq(),
            ts=time.time(), cost=serialize.cost_snapshot(client),
        ))
    except Exception as exc:  # noqa: BLE001 - surface any failure as a terminal frame
        handle.status = "error"
        handle.error = str(exc)
        handle.emit(serialize.frame(
            "error", {"message": str(exc)}, run_id=handle.id, seq=handle.next_seq(),
            ts=time.time(),
        ))
    finally:
        # Guarantee a terminal frame even on an abrupt (BaseException) thread death,
        # so a connected SSE stream can always end.
        if handle.status == "running":
            handle.status = "error"
            handle.error = handle.error or "worker terminated unexpectedly"
            handle.emit(serialize.frame(
                "error", {"message": handle.error}, run_id=handle.id,
                seq=handle.next_seq(), ts=time.time(),
            ))


def start_run(handle: RunHandle, client, develop_kwargs: dict) -> threading.Thread:
    """Spawn the daemon worker thread for ``handle`` and return it."""
    t = threading.Thread(
        target=run_pipeline_thread, args=(handle, client, develop_kwargs), daemon=True
    )
    t.start()
    return t
