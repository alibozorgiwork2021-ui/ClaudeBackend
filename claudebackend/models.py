"""Typed data structures passed between pipeline stages."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Risk = Literal["low", "medium", "high"]
Action = Literal["create", "modify", "delete"]


class VerifyResult(BaseModel):
    """Outcome of a deterministic verification pass.

    ``errors`` are failures (they make ``ok`` False); ``notes`` are non-fatal
    information such as a skipped test suite or a flagged-for-review decision.
    ``steps`` maps each verification step name (``"compile"``, ``"ruff"``,
    ``"pytest"``, ``"bandit"``) to a short status string (``"ok"``, ``"FAILED"``,
    ``"skipped"``, or a pytest pass summary like ``"18 passed"``).

    ``security_issues`` holds advisory SAST findings (e.g. from ``bandit``) for the
    whole tree. They never flip ``ok``: pre-existing repo code must not fail the
    build, and the blocking security gate runs per step on the Coder's new code.
    """

    ok: bool
    errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    steps: dict[str, str] = Field(default_factory=dict)
    security_issues: list[str] = Field(default_factory=list)


class FileResult(BaseModel):
    """A single file produced by the Coder."""

    path: str
    code: str
    notes: str = ""


class PlanStep(BaseModel):
    """One step of an execution plan: create, modify, or delete a single file.

    ``instructions`` is a precise, self-contained description of exactly what the
    Coder must do to ``path`` to advance the objective. ``depends_on`` lists the
    paths of earlier steps this one builds on, so the orchestrator can order
    dependencies before the files that use them.
    """

    path: str
    action: Action
    instructions: str
    rationale: str = ""
    risk: Risk = "low"
    depends_on: list[str] = Field(default_factory=list)


class ExecutionPlan(BaseModel):
    """The ordered plan the Planner agent produces for a user objective."""

    objective: str
    summary: str = ""
    steps: list[PlanStep]


class SecurityFinding(BaseModel):
    """One issue raised by the optional LLM security-review pass."""

    file: str
    severity: Risk = "low"
    issue: str
    recommendation: str = ""


class SecurityReview(BaseModel):
    """Outcome of the optional LLM security-review pass over the changed files.

    ``ok`` is True when no findings were raised. This pass is advisory: it never
    changes files and is only run when explicitly requested (``--security-review``).
    """

    ok: bool = True
    findings: list[SecurityFinding] = Field(default_factory=list)
