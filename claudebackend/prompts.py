"""Prompt text and builders for the Planner and Coder agents."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from claudebackend.models import PlanStep


# --- Planner ---

def planner_prompt(objective: str, graph_summary: str, dynamic: set[str]) -> str:
    """User message: the objective plus a map of the existing codebase to plan
    against. The Planner decides which files to create, modify, or delete."""
    lines = [
        "You are a senior backend software engineer and architect.",
        "",
        "OBJECTIVE:",
        objective.strip() or "(no objective provided)",
        "",
        "EXISTING CODEBASE MAP (paths are repo-relative):",
        graph_summary.rstrip() or "  (empty repository)",
    ]
    if dynamic:
        lines += [
            "",
            "These files use dynamic imports, so the dependency map may be "
            "incomplete; account for that: " + ", ".join(sorted(dynamic)),
        ]
    lines += [
        "",
        "Produce an ExecutionPlan that achieves the OBJECTIVE with the smallest "
        "set of changes that is correct and complete. The plan is an ordered list "
        "of steps; each step targets exactly one file and has an `action`:",
        "  - create: a new file that does not exist yet",
        "  - modify: an existing file that must change",
        "  - delete: an existing file that must be removed",
        "",
        "For each step set `path` (repo-relative), `action`, `instructions` (a "
        "precise, self-contained description of exactly what the Coder must do to "
        "that one file to advance the objective), `rationale` (why this step is "
        "needed), `risk` (low | medium | high), and `depends_on` (paths of earlier "
        "steps this one builds on, e.g. a module that must exist first). Order the "
        "steps so dependencies come before the files that use them. Do not include "
        "steps unrelated to the objective. Set the plan's `objective` to the "
        "objective above and `summary` to a one-paragraph description of your "
        "approach.",
    ]
    return "\n".join(lines)


# --- Coder ---

CODER_SYSTEM = (
    "You are a backend software engineer implementing exactly ONE step of an "
    "execution plan. You are given the overall objective, the step's instructions, "
    "the current contents of the target file (or a note that it is a new file), "
    "and READ-ONLY context from related files. Implement only what the step "
    "instructions require to advance the objective; keep the change focused and "
    "preserve unrelated existing behaviour. Match the surrounding code's style, "
    "imports, and conventions, and keep cross-file behaviour correct using the "
    "read-only context.\n\n"
    "Output ONLY the full new contents of the target file, with no prose, no "
    "explanation, and no Markdown code fence. Whenever you make an ambiguous "
    "architectural decision or a security-sensitive change (for example raw SQL "
    "queries, authentication or authorization logic, cryptography, secret or "
    "token handling, deserialization of untrusted input, or shelling out to a "
    "subprocess), add a brief `# CLAUDEBACKEND-REVIEW:` comment on the relevant "
    "line explaining the choice so a human can confirm it."
)


def deps_block_text(dependencies: dict[str, str]) -> str:
    """Read-only related-file context (a stable, cacheable block)."""
    lines = ["READ-ONLY CONTEXT (related files — do not output these):", ""]
    for path, src in dependencies.items():
        lines += [f"--- {path} ---", src, ""]
    return "\n".join(lines)


def step_block_text(
    objective: str,
    step: "PlanStep",
    target_source: str,
    target_version: str,
    prior_errors: list[str] | None = None,
    security_errors: list[str] | None = None,
    task_context: str | None = None,
    version_label: str = "Target Python version",
) -> str:
    """The step to implement + target file + (on retry) prior verifier errors.

    ``security_errors`` (only ever set on a retry) render a separate, prominent
    SECURITY AUDIT FAILURE block so a rejection for a vulnerability is unmistakable
    and distinct from a syntax/test failure. The Coder's *first* attempt never
    carries security text — security is the Verifier's concern, not the Coder's
    initial focus.

    ``task_context`` is run-wide context present from the FIRST attempt (unlike
    ``prior_errors``): the TDD watcher passes the failing pytest output here so the
    Coder sees exactly why the test fails.
    """
    if step.action == "create":
        target = target_source or "(new file — it does not exist yet)"
        header = "FILE TO CREATE — output ONLY the full contents of this file:"
    else:
        target = target_source
        header = (
            "FILE TO MODIFY — output ONLY the full, updated contents of this file:"
        )
    lines = [
        f"Objective: {objective}",
        f"{version_label}: {target_version}.",
        "",
        f"STEP ({step.action} {step.path}): {step.instructions}",
    ]
    if task_context:
        lines += [
            "",
            "FAILING TEST OUTPUT — implement code so this test passes; do NOT modify "
            "the test:",
            task_context,
        ]
    lines += [
        "",
        header,
        f"=== {step.path} ===",
        target,
    ]
    if prior_errors:
        lines += [
            "",
            "Your previous attempt failed verification with these errors; fix them:",
            *prior_errors,
        ]
    if security_errors:
        lines += [
            "",
            "SECURITY AUDIT FAILURE — your previous attempt introduced the security "
            "vulnerabilities below. Rewrite the file to fix them while still "
            "satisfying the step. Do NOT weaken or work around the fix; use safe, "
            "parameterised, and properly authorised constructs:",
            *security_errors,
        ]
    return "\n".join(lines)


# --- Red Team (per-step blocking security audit) ---

def red_team_prompt(
    step: "PlanStep",
    code: str,
    sast_findings: list[str] | None = None,
    vuln_patterns_hint: str | None = None,
) -> str:
    """User message: an attacker's-mindset review of one Coder-produced file.

    Returns a ``SecurityReview`` for just this file. The audit is static (reading
    the code), never executing it. ``vuln_patterns_hint`` names the
    language-specific dangerous constructs to call out (supplied by the driver), so
    the prompt is not hardcoded to one language's sinks.
    """
    deser = "unsafe deserialization of untrusted input"
    if vuln_patterns_hint:
        deser += f" ({vuln_patterns_hint})"
    lines = [
        "You are an offensive application-security engineer (red team) auditing a "
        "single file a teammate just wrote. Adopt an attacker's mindset: assume the "
        "inputs are hostile and look for a concrete way to exploit THIS code.",
        "",
        "Hunt specifically for: SQL/NoSQL injection, OS-command or template "
        "injection, broken access control / IDOR (missing ownership or permission "
        "checks), reflected or stored XSS, server-side request forgery (SSRF), path "
        "traversal, " + deser + ", weak or misused crypto, and hard-coded secrets "
        "or tokens.",
        "",
        f"FILE UNDER REVIEW: {step.path}",
        f"=== {step.path} ===",
        code,
        "",
    ]
    if sast_findings:
        lines += [
            "A static analyzer flagged the following on this file. Confirm "
            "the real, exploitable ones and ignore false positives:",
            *sast_findings,
            "",
        ]
    lines += [
        "Report a SecurityReview. Set `ok` to true ONLY if the file has no real, "
        f"exploitable issue. For each genuine issue add a finding with `file` "
        f"(use \"{step.path}\"), `severity` (low | medium | high — use medium/high "
        "for anything exploitable), `issue` (the vulnerability and where), and "
        "`recommendation` (the concrete fix). Do not invent issues or flag mere "
        "style; if the file is safe, return no findings.",
    ]
    return "\n".join(lines)


# --- Security reviewer (optional LLM pass) ---

def security_review_prompt(files: dict[str, str]) -> str:
    """User message: the changed files for an advisory LLM security review."""
    lines = [
        "You are a senior application-security engineer reviewing a code change.",
        "",
        "Review the following created/changed files for security issues — for "
        "example injection (SQL / OS command / template), authentication or "
        "authorization flaws, weak or misused cryptography, secret or token "
        "handling, unsafe deserialization of untrusted input, SSRF, path "
        "traversal, or shelling out to a subprocess with untrusted data.",
        "",
        "Report a SecurityReview: set `ok` to true only if you find no issues. For "
        "each real issue add a finding with `file`, `severity` (low | medium | "
        "high), `issue` (what and where), and `recommendation` (how to fix). Do "
        "not invent issues; if a file is fine, do not add a finding for it.",
        "",
    ]
    for path, src in files.items():
        lines += [f"=== {path} ===", src, ""]
    return "\n".join(lines)
