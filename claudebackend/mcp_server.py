"""MCP server exposing ClaudeBackend as a tool.

This is how Claude Code/Desktop, Cursor, Google Antigravity, Codex, and any other
MCP-capable agent use ClaudeBackend: they call the ``develop_backend_feature``
tool. Run it with ``claudebackend mcp`` (stdio transport).
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from claudebackend.config import resolve_models
from claudebackend.core.client import Client
from claudebackend.core.limits import input_budget_for
from claudebackend.orchestrator import develop_feature

mcp = FastMCP("claudebackend")


def _env_local() -> bool:
    return os.environ.get("CLAUDEBACKEND_LOCAL", "").strip().lower() in {"1", "true", "yes"}


def _run(
    path: str,
    objective: str,
    *,
    dry_run: bool = True,
    provider: str = "anthropic",
    model: str | None = None,
    init: bool = False,
    max_retries: int = 3,
    local: bool = False,
    security_gate: bool = True,
    security_review: bool = False,
    planner_model: str | None = None,
    coder_model: str | None = None,
    verifier_model: str | None = None,
    lang: str | None = None,
    client: Any = None,
) -> dict:
    # Air-gap: an explicit local=True OR a CLAUDEBACKEND_LOCAL=1 deployment (the
    # air-gapped Docker network) forces local-only mode and an Ollama backend, so
    # the server never reaches an external endpoint.
    local = bool(local) or _env_local()
    if local and provider == "anthropic":
        provider = "ollama"

    # ``develop_feature`` takes a concrete language; resolve "auto"/None here.
    from claudebackend.core.drivers import detect_lang

    resolved_lang = detect_lang(path) if not lang or lang == "auto" else lang

    models_cfg = resolve_models(
        default_model=model,
        cli_overrides={
            "planner": planner_model,
            "coder": coder_model,
            "verifier": verifier_model,
        },
        root=path,
    )
    primary_model = (
        model or models_cfg["coder"] or models_cfg["planner"] or models_cfg["verifier"]
    )
    max_context_tokens = (
        input_budget_for(models_cfg["coder"] or primary_model, local=True)
        if provider == "ollama"
        else None
    )

    if client is None:
        client = Client(provider=provider, model=primary_model, local=local)
    report = develop_feature(
        path,
        client=client,
        objective=objective,
        dry_run=dry_run,
        init=init,
        max_retries=max_retries,
        planner_model=models_cfg["planner"],
        coder_model=models_cfg["coder"],
        verifier_model=models_cfg["verifier"],
        max_context_tokens=max_context_tokens,
        security_review=security_review,
        security_gate=security_gate,
        lang=resolved_lang,
    )
    return {
        "objective": report.objective,
        "dry_run": report.dry_run,
        "branch": report.branch,
        "lang": report.lang,
        "project_ok": report.project_ok,
        "project_errors": report.project_errors,
        "created": report.created,
        "modified": report.modified,
        "deleted": report.deleted,
        "flagged": report.flagged,
        "unsafe": report.unsafe,
        "review": report.review,
        "summary": report.summary,
        "graph": report.graph_path,
        "diff": report.diff if report.dry_run else None,
        "cost": report.to_dict()["cost"],
        "security_issues": report.security_issues,
        "security": report.security.model_dump() if report.security is not None else None,
    }


@mcp.tool()
def develop_backend_feature(
    path: str,
    objective: str,
    dry_run: bool = True,
    provider: str = "anthropic",
    model: str | None = None,
    init: bool = False,
    max_retries: int = 3,
    local: bool = False,
    security_gate: bool = True,
    security_review: bool = False,
    planner_model: str | None = None,
    coder_model: str | None = None,
    verifier_model: str | None = None,
    lang: str | None = None,
) -> dict:
    """Develop a backend feature in a repository via an isolated Planner/Coder/Verifier pipeline.

    ``objective`` is a free-form goal, e.g. "Add JWT authentication" or "Refactor
    the SQLAlchemy models". The Planner decides which files to create, modify, or
    delete; the Coder implements each step; the Verifier runs py_compile + ruff +
    pytest as a deterministic safety net (up to ``max_retries`` Coder retries per
    step).

    dry_run=True (the default) previews the work and writes NOTHING to the repo —
    always start here; the result includes a unified ``diff``. Set dry_run=False to
    write the result onto a new git branch (requires a clean working tree; pass
    init=True for a non-git folder). provider/model select the LLM backend
    (anthropic by default; others need a model id). ``lang`` selects the source
    language (``auto`` — the default — detects python vs php from the repo's
    manifest; pass ``python`` or ``php`` to force it).

    A per-step security gate (bandit SAST + a Red Team LLM audit on the Coder's new
    code) runs by default after the deterministic checks; vulnerabilities are fed
    back to the Coder and, if unfixable within max_retries, the unsafe file is
    discarded (listed under ``unsafe``). Pass security_gate=False to disable it.

    For fully offline use set local=True (or run with CLAUDEBACKEND_LOCAL=1) to run
    against local Ollama with no external calls; planner_model/coder_model/
    verifier_model route specific local models per agent (verifier_model also runs
    the Red Team audit). security_review=True adds a separate advisory LLM security
    pass over the changed files.

    Returns a report dict with the objective, branch, project_ok/project_errors,
    the created/modified/deleted/flagged file lists, ``unsafe`` (files discarded by
    the security gate), files containing CLAUDEBACKEND-REVIEW markers, the summary,
    the topology graph path, the diff (dry-run only), a ``cost`` key (a dict when
    pricing is known; cost_usd is null when unknown; cost is null when the client
    reports no usage), ``security_issues`` (advisory SAST findings), and a
    ``security`` key (null unless security_review was requested).
    """
    return _run(
        path,
        objective,
        dry_run=dry_run,
        provider=provider,
        model=model,
        init=init,
        max_retries=max_retries,
        local=local,
        security_gate=security_gate,
        security_review=security_review,
        planner_model=planner_model,
        coder_model=coder_model,
        verifier_model=verifier_model,
        lang=lang,
    )


def run() -> None:
    """Run the MCP server over stdio."""
    mcp.run()
