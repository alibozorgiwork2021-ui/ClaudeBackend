"""Local TDD watcher daemon.

Watches a test directory; when a save leaves a failing test, it runs the pipeline
to implement the code that makes it pass — writing **in place** (no branch, no
commit) for a fast red→green inner loop.

Loop-safe by construction (the DON'T-infinite-loop requirement):
- only saves under the watched *test* dir trigger a run (the agent writes *source*,
  not tests, so its own writes never retrigger the watcher);
- runs are serialised — file events that arrive while a run is in progress are
  ignored;
- a test that is still red after ``max_retries`` simply halts and waits for the
  next human edit (it never re-triggers itself).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from claudebackend.core.client import Client
from claudebackend.orchestrator import develop_feature
from claudebackend.tdd import find_first_failure, tdd_objective

logger = logging.getLogger(__name__)

_DEBOUNCE_SECONDS = 1.0


def _default_client_factory() -> Client:
    return Client()


def run_once(root, *, max_retries: int = 3, client_factory=_default_client_factory,
             on_event=None, security_gate: bool = True) -> str:
    """One TDD cycle. Returns:

    - ``"green"``   — the suite already passes (nothing to do),
    - ``"fixed"``   — the previously-failing test now passes,
    - ``"unfixed"`` — still failing after ``max_retries`` (halt; wait for a human).
    """
    root = Path(root)
    failure = find_first_failure(root)
    if failure is None:
        logger.info("suite is green - nothing to do")
        return "green"
    nodeid, output = failure
    logger.info("failing test %s - implementing a fix in place", nodeid)
    develop_feature(
        root,
        client=client_factory(),
        objective=tdd_objective(nodeid, output),
        max_retries=max_retries,
        apply_in_place=True,
        assume_yes=True,
        task_context=output,
        security_gate=security_gate,
        on_event=on_event,
    )
    after = find_first_failure(root)
    if after is None or after[0] != nodeid:
        logger.info("%s now passes", nodeid)
        return "fixed"
    logger.warning(
        "%s still failing after %d retries - halting; edit the code or the test "
        "and save again", nodeid, max_retries,
    )
    return "unfixed"


def watch(root=".", test_dir: str = "tests", *, max_retries: int = 3,
          on_event=None) -> None:
    """Block, watching ``test_dir`` for ``.py`` saves; run a TDD cycle on each."""
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise RuntimeError(
            "watch mode needs the 'watchdog' package. Install it with: "
            "pip install claudebackend[watch]"
        ) from exc

    root = Path(root).resolve()
    td = Path(test_dir)
    watch_path = td if td.is_absolute() else root / td
    if not watch_path.exists():
        raise RuntimeError(f"watch directory does not exist: {watch_path}")

    state = {"running": False, "last": 0.0}

    class _Handler(FileSystemEventHandler):
        def on_any_event(self, event) -> None:
            if event.is_directory or not str(event.src_path).endswith(".py"):
                return
            if state["running"]:
                return  # ignore events fired by/while a run is in progress
            now = time.monotonic()
            if now - state["last"] < _DEBOUNCE_SECONDS:
                return
            state["last"] = now
            state["running"] = True
            try:
                run_once(root, max_retries=max_retries, on_event=on_event)
            except Exception:  # noqa: BLE001 - keep the daemon alive across run errors
                logger.exception("TDD run failed; waiting for the next save")
            finally:
                state["running"] = False

    observer = Observer()
    observer.schedule(_Handler(), str(watch_path), recursive=True)
    observer.start()
    logger.info("watching %s for failing tests (Ctrl-C to stop)", watch_path)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:  # pragma: no cover - interactive
        logger.info("stopping watcher")
    finally:
        observer.stop()
        observer.join()
