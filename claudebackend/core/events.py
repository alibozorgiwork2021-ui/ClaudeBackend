"""Typed progress events emitted by the development pipeline.

The orchestrator emits these events to an optional reporter callback as work
proceeds.  Each event is a frozen dataclass so callers can pattern-match on
type without risk of mutation.  No external dependencies — stdlib only.

Typical usage::

    def on_event(event: Event) -> None:
        if isinstance(event, FileDone):
            print(f"{'OK' if event.ok else 'FLAGGED'}: {event.path}")

    develop_feature(..., on_event=on_event)
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "DepGraphDone",
    "PlanDone",
    "StepStart",
    "FileRetry",
    "SecurityReject",
    "FileDone",
    "ProjectVerifyResult",
    "Commit",
    "Event",
]


@dataclass(frozen=True)
class DepGraphDone:
    """The codebase map has been built.

    ``files`` — total files scanned into the graph (all kinds).
    ``dynamic`` — count of files that use dynamic imports (``importlib``,
    ``__import__``, etc.) detected by the graph builder.
    ``kinds`` — count of nodes per kind, e.g.
    ``{"python": 12, "orm": 2, "dockerfile": 1, "config": 3}``.
    ``graph`` — optional vis-network payload (``{"nodes": [...], "edges": [...]}``)
    captured from the exact Graph the Planner saw, so a live dashboard can render
    the topology even for a dry run (whose throwaway workdir is gone afterwards).
    ``None`` for callers that do not need it (the CLI/MCP ignore it).
    """

    files: int
    dynamic: int
    kinds: dict[str, int] = field(default_factory=dict)
    graph: dict | None = None


@dataclass(frozen=True)
class PlanDone:
    """Planner has produced the execution plan.

    ``steps`` — total steps in the plan.
    ``high_risk`` — number of steps the planner marked as high risk.
    """

    steps: int
    high_risk: int


@dataclass(frozen=True)
class StepStart:
    """About to begin step ``index`` of ``total``.

    ``path`` — the file this step targets; ``action`` is create/modify/delete.
    """

    index: int
    total: int
    path: str
    action: str


@dataclass(frozen=True)
class FileRetry:
    """A step's implementation is being retried.

    ``attempt`` is 1-based: the first retry is ``attempt=1``.
    """

    path: str
    attempt: int


@dataclass(frozen=True)
class SecurityReject:
    """The per-step security gate rejected a candidate file as unsafe.

    ``attempt`` is 1-based (the first rejection is ``attempt=1``). ``issues`` are
    short, human-readable descriptions of the blocking vulnerabilities that were
    fed back to the Coder for the next retry.
    """

    path: str
    attempt: int
    issues: tuple[str, ...]


@dataclass(frozen=True)
class FileDone:
    """A step finished processing.

    ``ok=True`` means the file was produced and passed the syntax gate;
    ``ok=False`` means it was flagged for manual review after exhausting retries.
    """

    path: str
    ok: bool


@dataclass(frozen=True)
class ProjectVerifyResult:
    """Project-wide verification finished.

    ``steps`` maps each verification step name to a status string, e.g.
    ``{"compile": "ok", "ruff": "ok", "pytest": "18 passed"}``.
    ``ok`` is the overall pass/fail result.

    Note: ``dict`` fields on a frozen dataclass are unhashable by default,
    which is intentional — these events are never placed in sets or dicts.
    """

    steps: dict[str, str]
    ok: bool


@dataclass(frozen=True)
class Commit:
    """A step's file was committed to git (live runs only).

    ``paths`` — the file paths included in the commit.
    """

    paths: tuple[str, ...]


# Union type alias for the reporter callback signature.
Event = DepGraphDone | PlanDone | StepStart | FileRetry | SecurityReject | FileDone | ProjectVerifyResult | Commit
