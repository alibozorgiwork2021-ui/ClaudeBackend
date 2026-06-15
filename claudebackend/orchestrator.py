"""The deterministic development pipeline.

Wiring: clean-tree / repo policy -> cost preflight -> codebase map (depgraph) ->
Planner (decides the steps) -> per step (build context -> Coder -> syntax gate ->
retry) -> project-wide verify (the real gate) -> topology graph -> per-step
commits + summary. ``--dry-run`` runs the whole thing on a throwaway copy and
writes nothing to the user's repo.

The three agents stay strictly isolated: the Planner produces an ``ExecutionPlan``
from the objective, the Coder implements one step at a time, and the Verifier is
the deterministic safety net. None of them are merged into a single call.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from claudebackend.agents import coder, security_auditor, security_reviewer
from claudebackend.agents.planner import plan as make_plan
from claudebackend.core import events, git
from claudebackend.core.context_builder import build_context
from claudebackend.core.depgraph import build_graph
from claudebackend.core.drivers import get_driver
from claudebackend.core.graphviz import _nodes_edges, render_graph
from claudebackend.core.limits import ContextWindowExceededError
from claudebackend.core.verifier import (
    format_sast,
    scan_code,
    verify_project,
)
from claudebackend.models import ExecutionPlan, PlanStep, SecurityReview, VerifyResult

if TYPE_CHECKING:
    from claudebackend.core.pricing import CostReport

REVIEW_MARKER = "CLAUDEBACKEND-REVIEW"

logger = logging.getLogger(__name__)


def _noop_event(event) -> None:
    return None


class OrchestratorError(RuntimeError):
    """A run could not start or was aborted (policy / preflight)."""


@dataclass
class DevReport:
    objective: str = ""
    branch: str | None = None
    target_version: str = ""
    lang: str = ""
    created: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    flagged: list[str] = field(default_factory=list)
    unsafe: list[str] = field(default_factory=list)
    review: list[str] = field(default_factory=list)
    dynamic: list[str] = field(default_factory=list)
    security_issues: list[str] = field(default_factory=list)
    project_ok: bool = False
    project_errors: list[str] = field(default_factory=list)
    project_notes: list[str] = field(default_factory=list)
    summary: str = ""
    dry_run: bool = False
    diff: str | None = None
    cost: "CostReport | None" = None
    security: SecurityReview | None = None
    verify_steps: dict[str, str] = field(default_factory=dict)
    graph_path: str | None = None

    def to_dict(self) -> dict:
        """Stable, versioned, JSON-serialisable view of the report (no I/O)."""
        if self.cost is None:
            cost = None
        else:
            u = self.cost.usage
            cost = {
                "input_tokens": u.input_tokens,
                "output_tokens": u.output_tokens,
                "cache_read_tokens": u.cache_read_tokens,
                "cache_write_tokens": u.cache_write_tokens,
                "cost_usd": self.cost.cost_usd if self.cost.pricing_known else None,
                "pricing_known": self.cost.pricing_known,
                "cache_hit_ratio": self.cost.cache_hit_ratio,
                "calls": u.calls,
            }
        return {
            "schema_version": 2,
            # "ok" is the stable top-level gate for CI (e.g. jq -e .ok); it
            # mirrors project_ok, which is kept too for symmetry with the field.
            "ok": self.project_ok,
            "objective": self.objective,
            "dry_run": self.dry_run,
            "branch": self.branch,
            "target_version": self.target_version,
            "lang": self.lang,
            "project_ok": self.project_ok,
            "project_errors": self.project_errors,
            "project_notes": self.project_notes,
            "created": self.created,
            "modified": self.modified,
            "deleted": self.deleted,
            "flagged": self.flagged,
            "unsafe": self.unsafe,
            "review": self.review,
            "dynamic": self.dynamic,
            "security_issues": self.security_issues,
            "summary": self.summary,
            "verify_steps": self.verify_steps,
            "graph": self.graph_path,
            "cost": cost,
            "security": self.security.model_dump() if self.security is not None else None,
            "diff": self.diff,
        }


def _estimate_tokens(root: Path, driver) -> int:
    """Cheap offline heuristic (~4 bytes/token) for the cost-gate preflight."""
    total = 0
    for ext in driver.source_exts:
        total += sum(p.stat().st_size for p in root.rglob(f"*{ext}"))
    return total // 4


def _write(path: Path, code: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not code.endswith("\n"):
        code += "\n"
    path.write_text(code, encoding="utf-8")


def _verify_code(code: str, driver) -> VerifyResult:
    """Syntax-gate a candidate file via the driver, without touching the real file.

    Python uses in-process ``compile()``; PHP uses ``php -l`` (degrading to ok when
    the toolchain is absent) — the driver decides.
    """
    with tempfile.NamedTemporaryFile(
        "w", suffix=driver.sast_tmp_suffix(), delete=False, encoding="utf-8"
    ) as fh:
        fh.write(code)
        tmp = Path(fh.name)
    try:
        sc = driver.syntax_check(tmp)
        return VerifyResult(ok=sc.ok, errors=[sc.error] if sc.error else [])
    finally:
        tmp.unlink(missing_ok=True)


def _order_steps(steps: list[PlanStep]) -> list[PlanStep]:
    """Order steps so a step's ``depends_on`` paths come first (stable; cycles and
    unknown deps fall back to plan order)."""
    index = {s.path: i for i, s in enumerate(steps)}
    visited: set[int] = set()
    temp: set[int] = set()
    order: list[int] = []

    def visit(i: int) -> None:
        if i in visited or i in temp:
            return
        temp.add(i)
        for dep in steps[i].depends_on:
            j = index.get(dep)
            if j is not None and j != i:
                visit(j)
        temp.discard(i)
        visited.add(i)
        order.append(i)

    for i in range(len(steps)):
        visit(i)
    return [steps[i] for i in order]


def _classify_security(sast, audit: SecurityReview) -> tuple[list[str], list]:
    """Split the security signal for one file into blocking issues vs review-only.

    Blocking = any Red Team finding rated medium/high, plus any SAST finding that
    is high severity AND at least medium confidence (a low-confidence SAST finding
    the Red Team confirms surfaces as a medium/high audit finding, so it blocks
    too). Review-only = the leftover low-confidence / low-severity SAST warnings
    the Red Team did not confirm — these get a CLAUDEBACKEND-REVIEW marker, not a
    block, so the pipeline never loops forever on an unprovable warning.
    """
    blocking: list[str] = []
    for f in audit.findings:
        if f.severity in ("medium", "high"):
            rec = f" -> {f.recommendation}" if f.recommendation else ""
            blocking.append(f"[{f.severity}] {f.issue}{rec}")
    review = []
    for s in sast:
        if s.severity == "HIGH" and s.confidence in ("MEDIUM", "HIGH"):
            # SastFinding.__str__ renders "<test_id> [SEV/CONF] line N: text" for
            # any language's SAST (bandit, PHP regex rules, ...).
            blocking.append(str(s))
        else:
            review.append(s)
    return blocking, review


def _inject_review_markers(code: str, review, driver) -> str:
    """Append CLAUDEBACKEND-REVIEW markers, in the language's comment syntax, for
    unresolved low-confidence SAST warnings."""
    if not review:
        return code
    notes = [
        driver.review_marker_line(
            REVIEW_MARKER, f"{s.test_id} (low confidence) line {s.line}: {s.text}"
        )
        for s in review
    ]
    body = code.rstrip("\n")
    header = (
        f"{driver.comment_prefix()} --- security review "
        "(unresolved low-confidence warnings) ---"
    )
    return body + "\n\n" + header + "\n" + "\n".join(notes) + "\n"


def _apply_step(client, workdir: Path, graph, objective: str, step: PlanStep,
                tv: str, max_retries: int, on_event=_noop_event,
                coder_model: str | None = None,
                verifier_model: str | None = None,
                security_gate: bool = True,
                max_context_tokens: int | None = None,
                task_context: str | None = None,
                driver=None) -> str:
    """Run one plan step. Returns created/modified/deleted/flagged/unsafe.

    Each attempt: Coder implements -> deterministic syntax gate -> (source files
    only, when enabled) the security gate (SAST + Red Team). A blocking security finding
    feeds the vulnerability back to the Coder and retries. Exhausting retries on a
    security block DISCARDS the unsafe candidate (writes nothing) and returns
    "unsafe"; exhausting them on a syntax failure leaves the best attempt on disk
    for review and returns "flagged".
    """
    target = workdir / step.path
    if step.action == "delete":
        if target.exists():
            target.unlink()
        on_event(events.FileDone(path=step.path, ok=True))
        logger.debug("deleted %s", step.path)
        return "deleted"

    if driver is None:
        driver = get_driver("python")
    is_source = driver.is_source_file(step.path)
    existed = target.exists()
    errors = None
    security_errors = None
    flag_code = None  # best attempt to leave on disk if we flag for syntax review
    last_was_security = False
    for attempt in range(max_retries):
        if attempt > 0:
            on_event(events.FileRetry(path=step.path, attempt=attempt))
            head = (security_errors or errors or [""])[0][:200]
            logger.debug("retry %s attempt %d: %s", step.path, attempt, head)
        try:
            ctx = build_context(objective, step, graph, workdir, tv,
                                prior_errors=errors, security_errors=security_errors,
                                max_context_tokens=max_context_tokens,
                                task_context=task_context, driver=driver)
        except ContextWindowExceededError as exc:
            # Deterministic — retrying won't shrink the file; flag immediately.
            errors = [str(exc)]
            last_was_security = False
            logger.info("context window exceeded for %s: %s", step.path, exc)
            break
        try:
            result = coder.implement(client, step, ctx, model=coder_model)
        except coder.CoderError as exc:
            errors = [str(exc)]
            security_errors = None
            last_was_security = False
            continue
        # 1. Deterministic syntax gate (source files only). Other file kinds rely
        #    on the project-wide verify (and human review) instead of py_compile.
        vr = _verify_code(result.code, driver) if is_source else VerifyResult(ok=True)
        if not vr.ok:
            flag_code = result.code
            errors = vr.errors
            security_errors = None
            last_was_security = False
            continue
        # 2. Security gate (Red Team + SAST), AFTER the deterministic gate passes.
        if security_gate and is_source:
            sast = scan_code(result.code, driver)
            audit = security_auditor.audit(
                client, step, result.code, format_sast(sast), model=verifier_model,
                vuln_patterns_hint=driver.vuln_patterns_hint(),
            )
            blocking, review = _classify_security(sast, audit)
            if blocking:
                security_errors = blocking
                errors = None
                last_was_security = True
                on_event(events.SecurityReject(
                    path=step.path, attempt=attempt + 1, issues=tuple(blocking),
                ))
                logger.warning("SECURITY: rejected %s (attempt %d): %s",
                               step.path, attempt + 1, blocking[0][:200])
                continue
            result.code = _inject_review_markers(result.code, review, driver)
        _write(target, result.code)
        on_event(events.FileDone(path=step.path, ok=True))
        logger.debug("implemented %s", step.path)
        return "modified" if existed else "created"

    if last_was_security:
        # Discard the unsafe candidate: write nothing. A modify-step keeps its safe
        # original on disk; a create-step file is never created.
        on_event(events.FileDone(path=step.path, ok=False))
        logger.warning("SECURITY: discarded unsafe %s after %d attempts",
                       step.path, max_retries)
        return "unsafe"
    if flag_code is not None:  # leave the best attempt on disk for review
        _write(target, flag_code)
    on_event(events.FileDone(path=step.path, ok=False))
    logger.info("flagged %s after %d attempts", step.path, max_retries)
    return "flagged"


def _scan_review_markers(workdir: Path, paths: list[str]) -> list[str]:
    found = []
    for p in paths:
        fp = workdir / p
        if not fp.exists():
            continue
        if REVIEW_MARKER in fp.read_text(encoding="utf-8", errors="replace"):
            found.append(p)
    return found


def _build_summary(report: "DevReport", plan: ExecutionPlan) -> str:
    risk = {s.path: (s.risk, s.rationale) for s in plan.steps}
    lines = [
        "# ClaudeBackend - development report",
        "",
        f"Objective: {report.objective}",
        f"Branch: {report.branch or '(dry run)'}",
        f"Target: {report.target_version}",
        "",
        "## Result",
        f"Project verification: {'PASSED' if report.project_ok else 'FAILED'}",
    ]
    for e in report.project_errors:
        lines.append("    " + e.replace("\n", "\n    "))
    for n in report.project_notes:
        lines.append(f"- note: {n}")
    if plan.summary:
        lines += ["", "## Approach", "", plan.summary]

    def section(title: str, paths: list[str]) -> list[str]:
        if not paths:
            return []
        out = ["", f"## {title} ({len(paths)})"]
        for p in paths:
            r, why = risk.get(p, ("?", ""))
            out.append(f"- {p} - risk: {r}" + (f" - {why}" if why else ""))
        return out

    lines += section("Created", report.created)
    lines += section("Modified", report.modified)
    lines += section("Deleted", report.deleted)
    if report.unsafe:
        lines += [
            "",
            f"## SECURITY — discarded unsafe files ({len(report.unsafe)})",
            "The Coder could not produce a safe implementation within the retry "
            "budget; these changes were DISCARDED (nothing was written for them):",
        ]
        lines += [f"- {p}" for p in report.unsafe]
    if report.flagged:
        lines += ["", f"## Flagged (failed verification after retries) ({len(report.flagged)})"]
        lines += [f"- {p}" for p in report.flagged]
    if report.review:
        lines += ["", "## Needs human review"]
        for p in report.review:
            lines.append(f"- {p} contains {REVIEW_MARKER} marker(s)")
    if report.security_issues:
        lines += ["", f"## SAST findings (advisory, bandit) ({len(report.security_issues)})"]
        lines += [f"- {s}" for s in report.security_issues]
    if report.dynamic:
        lines += ["", "## Dynamic imports (codebase map may be incomplete)"]
        lines += [f"- {p}" for p in report.dynamic]
    lines += ["", "See DEV_GRAPH.md for the project topology graph."]
    return "\n".join(lines) + "\n"


def _run_pipeline(client, workdir: Path, objective: str, tv: str, max_retries: int,
                  report: "DevReport", on_event=_noop_event,
                  planner_model: str | None = None, coder_model: str | None = None,
                  verifier_model: str | None = None,
                  max_context_tokens: int | None = None,
                  security_review: bool = False,
                  security_gate: bool = True,
                  task_context: str | None = None,
                  driver=None) -> None:
    """Plan -> apply every step -> project verify -> summary. Mutates report."""
    if driver is None:
        driver = get_driver("python")
    graph = build_graph(workdir, driver=driver)
    report.dynamic = sorted(graph.dynamic)
    kinds: dict[str, int] = {}
    for k in graph.kinds.values():
        kinds[k] = kinds.get(k, 0) + 1
    g_nodes, g_edges = _nodes_edges(graph)
    on_event(events.DepGraphDone(
        files=len(graph.kinds), dynamic=len(graph.dynamic), kinds=kinds,
        graph={"nodes": g_nodes, "edges": g_edges},
    ))
    logger.info("graph: %d files, %d dynamic, kinds=%s",
                len(graph.kinds), len(graph.dynamic), kinds)

    plan = make_plan(client, objective, graph, model=planner_model)
    steps = _order_steps(plan.steps)
    high_risk = sum(1 for s in steps if s.risk == "high")
    on_event(events.PlanDone(steps=len(steps), high_risk=high_risk))
    logger.info("plan: %d steps, %d high-risk", len(steps), high_risk)

    touched: list[tuple[str, str]] = []
    for i, step in enumerate(steps, 1):
        on_event(events.StepStart(
            index=i, total=len(steps), path=step.path, action=step.action,
        ))
        logger.debug("step %d/%d: %s %s", i, len(steps), step.action, step.path)
        outcome = _apply_step(client, workdir, graph, objective, step, tv,
                              max_retries, on_event, coder_model=coder_model,
                              verifier_model=verifier_model,
                              security_gate=security_gate,
                              max_context_tokens=max_context_tokens,
                              task_context=task_context, driver=driver)
        getattr(report, outcome).append(step.path)
        # "unsafe" files were discarded (nothing written) so there is nothing to
        # commit; every other outcome touched the tree.
        if outcome != "unsafe":
            touched.append((step.action, step.path))

    project = verify_project(workdir, tv, driver=driver)
    report.project_ok = project.ok
    report.project_errors = project.errors
    report.project_notes = project.notes
    report.security_issues = project.security_issues
    report.verify_steps = project.steps
    on_event(events.ProjectVerifyResult(steps=project.steps, ok=project.ok))
    logger.info("project verify: %s", "PASSED" if project.ok else "FAILED")

    report.review = _scan_review_markers(
        workdir, report.created + report.modified + report.flagged
    )

    if security_review:
        changed = report.created + report.modified + report.flagged
        files = {}
        for p in changed:
            fp = workdir / p
            if fp.exists():
                files[p] = fp.read_text(encoding="utf-8", errors="replace")
        report.security = security_reviewer.review(client, files, model=verifier_model)
        logger.info(
            "security review: %s (%d findings)",
            "ok" if report.security.ok else "issues found",
            len(report.security.findings),
        )

    report.summary = _build_summary(report, plan)
    report._touched = touched


def develop_feature(
    root,
    *,
    client,
    objective: str,
    target_version: str | None = None,
    max_retries: int = 3,
    dry_run: bool = False,
    init: bool = False,
    assume_yes: bool = False,
    cost_confirm=None,
    cost_warn_tokens: int = 500_000,
    on_event=None,
    planner_model: str | None = None,
    coder_model: str | None = None,
    verifier_model: str | None = None,
    max_context_tokens: int | None = None,
    security_review: bool = False,
    security_gate: bool = True,
    branch_name: str | None = None,
    apply_in_place: bool = False,
    task_context: str | None = None,
    lang: str = "python",
) -> DevReport:
    on_event = on_event or _noop_event
    root = Path(root)
    driver = get_driver(lang)
    pipeline_kwargs = dict(
        planner_model=planner_model,
        coder_model=coder_model,
        verifier_model=verifier_model,
        max_context_tokens=max_context_tokens,
        security_review=security_review,
        security_gate=security_gate,
        task_context=task_context,
        driver=driver,
    )
    tv = target_version or driver.default_version()

    # Cost preflight.
    estimate = _estimate_tokens(root, driver)
    if estimate > cost_warn_tokens and not assume_yes:
        if cost_confirm is None or not cost_confirm(estimate):
            raise OrchestratorError(
                f"aborted: estimated ~{estimate} input tokens exceeds the "
                f"{cost_warn_tokens} threshold"
            )

    report = DevReport(objective=objective, target_version=tv, dry_run=dry_run, lang=lang)

    # In-place mode (the TDD watcher): write straight into the working tree with no
    # branch and no commits, so the developer sees the test go green immediately and
    # keeps full control of staging/committing. Tolerates a dirty tree by design.
    if apply_in_place:
        _run_pipeline(client, root, objective, tv, max_retries, report,
                      on_event=on_event, **pipeline_kwargs)
        if hasattr(client, "cost_report"):
            report.cost = client.cost_report()
        return report

    if dry_run:
        tmp = Path(tempfile.mkdtemp(prefix="claudebackend-dry-"))
        workdir = tmp / root.name
        shutil.copytree(root, workdir, ignore=shutil.ignore_patterns(".git"))
        try:
            git.init_baseline(workdir)  # throwaway, just to compute a diff
            _run_pipeline(client, workdir, objective, tv, max_retries, report,
                          on_event=on_event, **pipeline_kwargs)
            report.diff = git.diff_all(workdir)  # incl. created/deleted files
            md_path, _ = render_graph(build_graph(workdir, driver=driver), workdir)
            report.graph_path = md_path.name
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if hasattr(client, "cost_report"):
            report.cost = client.cost_report()
        return report

    # Live run -- never touch a dirty tree; refuse a non-repo unless init.
    if not git.is_repo(root):
        if not init:
            raise OrchestratorError(
                "target is not a git repository; pass init=True (--init) to "
                "create a baseline commit before making changes"
            )
        git.init_baseline(root)
    else:
        git.require_clean_tree(root)

    report.branch = branch_name or git.branch_name()
    git.create_branch(root, report.branch)

    _run_pipeline(client, root, objective, tv, max_retries, report, on_event=on_event,
                  **pipeline_kwargs)

    # Commit per step only after the project-wide verify has run.
    for action, path in report._touched:
        git.commit_module(root, [path], f"ClaudeBackend: {action} {path}")
        on_event(events.Commit(paths=(path,)))
    md_path, html_path = render_graph(build_graph(root, driver=driver), root)
    report.graph_path = md_path.name
    git.commit_module(root, [md_path.name, html_path.name],
                      "ClaudeBackend: project topology graph")
    git.write_summary(root, report.summary)
    if hasattr(client, "cost_report"):
        report.cost = client.cost_report()
    return report
