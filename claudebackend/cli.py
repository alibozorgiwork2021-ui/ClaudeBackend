"""Command-line entry point for ClaudeBackend."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import typer

from claudebackend.config import resolve_models
from claudebackend.core import events
from claudebackend.core.client import (
    SUPPORTED_PROVIDERS,
    Client,
    ProviderConfigError,
    SubscriptionAuthError,
)
from claudebackend.core.git import GitError
from claudebackend.core.github import GitHubError
from claudebackend.core.limits import input_budget_for
from claudebackend.orchestrator import DevReport, OrchestratorError, develop_feature

app = typer.Typer(
    help="ClaudeBackend - universal multi-agent backend development system.",
    add_completion=False,
    no_args_is_help=True,
)


@app.callback()
def _root() -> None:
    """Keep ``develop`` a named subcommand (so `claudebackend develop PATH` works)."""


def _safe(text: str) -> str:
    """Make arbitrary text printable on a legacy (cp1252) console."""
    enc = sys.stdout.encoding or "utf-8"
    return text.encode(enc, errors="replace").decode(enc)


def _configure_logging(verbose: bool, quiet: bool) -> None:
    """Attach a single stderr handler to the ``claudebackend`` logger.

    Logs ALWAYS go to stderr; stdout is reserved for progress + JSON.  Safe to
    call more than once per process: any handler we previously attached is
    removed first so we never duplicate output.
    """
    logger = logging.getLogger("claudebackend")
    for h in list(logger.handlers):
        if getattr(h, "_claudebackend_cli", False):
            logger.removeHandler(h)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    handler._claudebackend_cli = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.ERROR if quiet else logging.WARNING)


def _is_ci() -> bool:
    """True when running under a CI runner (GitHub Actions or generic ``CI=true``)."""
    if os.environ.get("CI", "").strip().lower() in {"1", "true", "yes"}:
        return True
    return os.environ.get("GITHUB_ACTIONS", "").strip().lower() == "true"


def humantok(n: int) -> str:
    """Format a token count compactly: 1_500_000 -> '1.50M', 2_300 -> '2k'."""
    if n >= 1_000:
        thousands = round(n / 1_000)
        if thousands >= 1_000:  # rounds up to a million (e.g. 999_999 -> 1.00M)
            return f"{n / 1e6:.2f}M"
        return f"{thousands}k"
    return str(n)


class _ConsoleReporter:
    """Render development-pipeline progress events to stdout.

    Passed as ``on_event`` to :func:`develop_feature`.  When ``quiet`` is set it
    is a no-op for every event (the summary and cost line are printed by
    :func:`develop`, not here).  TTY output renders the develop phase in place
    (carriage return); non-TTY output prints one compact line per phase to keep
    piped logs clean.
    """

    def __init__(self, quiet: bool) -> None:
        self.quiet = quiet
        self._tty = sys.stdout.isatty()
        self._width = 0  # widest [3/4] line so far, for clearing
        self._pending_inplace = False  # an in-place line awaits a newline
        self._last_step = (0, 0, "")

    def __call__(self, event: events.Event) -> None:
        if self.quiet:
            return
        if isinstance(event, events.DepGraphDone):
            self._depgraph(event)
        elif isinstance(event, events.PlanDone):
            typer.echo(_safe(
                f"[2/4] plan: {event.steps} steps ({event.high_risk} high-risk)"
            ))
        elif isinstance(event, events.StepStart):
            self._step_start(event)
        elif isinstance(event, events.FileRetry):
            self._file_retry(event)
        elif isinstance(event, events.SecurityReject):
            self._security_reject(event)
        elif isinstance(event, events.ProjectVerifyResult):
            self._verify(event)
        # Commit -> silent.

    def _depgraph(self, event: events.DepGraphDone) -> None:
        parts = ", ".join(f"{k} {v}" for k, v in event.kinds.items()) or "0"
        typer.echo(_safe(
            f"[1/4] graph: {event.files} files ({parts}), {event.dynamic} dynamic"
        ))

    def _bar(self, index: int, total: int) -> str:
        filled = round(10 * index / total) if total else 0
        filled = max(0, min(10, filled))
        return "#" * filled + "-" * (10 - filled)

    def _step_line(self, index: int, total: int, label: str, suffix: str = "") -> str:
        return (
            f"[3/4] develop  {self._bar(index, total)}  "
            f"step {index}/{total}  {label}{suffix}"
        )

    def _render_inplace(self, line: str, last: bool) -> None:
        """TTY: redraw *line* in place, padding to clear any stale characters."""
        self._width = max(self._width, len(line))
        padded = line.ljust(self._width)
        typer.echo(_safe("\r" + padded), nl=False)
        self._pending_inplace = True
        if last:
            typer.echo("")  # fresh line so phase 4 starts clean
            self._pending_inplace = False

    def _step_start(self, event: events.StepStart) -> None:
        label = f"{event.action} {event.path}"
        if self._tty:
            self._last_step = (event.index, event.total, label)
            self._render_inplace(
                self._step_line(event.index, event.total, label),
                last=event.index == event.total,
            )
        elif event.index == 1:
            typer.echo(_safe(f"[3/4] develop: {event.total} steps"))

    def _file_retry(self, event: events.FileRetry) -> None:
        if not self._tty:
            # Retries are logged at DEBUG to stderr by the orchestrator, so the
            # non-TTY reporter stays silent on stdout to keep piped logs clean.
            return
        index, total, label = self._last_step
        self._render_inplace(
            self._step_line(index, total, label, f" (retry {event.attempt})"),
            last=False,
        )

    def _security_reject(self, event: events.SecurityReject) -> None:
        if self._pending_inplace:
            typer.echo("")  # close any open in-place [3/4] line first
            self._pending_inplace = False
        issue = event.issues[0] if event.issues else "unsafe code"
        typer.echo(_safe(
            f"  ! SECURITY: {event.path} rejected (attempt {event.attempt}): {issue}"
        ))

    def _verify(self, event: events.ProjectVerifyResult) -> None:
        if self._pending_inplace:
            typer.echo("")  # close any open in-place [3/4] line first
            self._pending_inplace = False

        parts = [
            f"{key} {'OK' if value == 'ok' else value}"
            for key, value in event.steps.items()
        ]
        typer.echo(_safe("[4/4] verify: " + " | ".join(parts)))


def _cost_line(report: DevReport) -> str | None:
    """The final token/cost line, or None when there is nothing to report."""
    cost = report.cost
    if cost is None:
        return None
    u = cost.usage
    base = f"Cost  in {humantok(u.input_tokens)}  out {humantok(u.output_tokens)}"
    if cost.pricing_known:
        line = (
            f"{base}  ~${cost.cost_usd:.2f}  "
            f"(cache hit {round(cost.cache_hit_ratio * 100)}%)"
        )
        if cost.partial:
            line += "  (partial)"
        return line
    return f"{base}  (cost unavailable for model {cost.model})"


def _print_report(report: DevReport) -> None:
    typer.echo("")
    if report.dry_run:
        typer.echo("Dry run - no changes were written to your repository.")
    elif report.branch:
        typer.echo(f"Branch: {report.branch}")
    typer.echo(
        "Project verification: " + ("PASSED" if report.project_ok else "FAILED")
    )
    changed = (
        f"Created {len(report.created)}, modified {len(report.modified)}, "
        f"deleted {len(report.deleted)} file(s)"
    )
    typer.echo(changed)
    if report.flagged:
        typer.echo("Flagged (failed verification): " + ", ".join(report.flagged))
    if report.unsafe:
        typer.echo(
            "Discarded (unsafe, not written): " + ", ".join(report.unsafe)
        )
    if report.review:
        typer.echo("Review markers in: " + ", ".join(report.review))
    if report.security_issues:
        typer.echo(f"SAST findings (advisory): {len(report.security_issues)}")
    if report.security is not None:
        sec = report.security
        if sec.ok:
            typer.echo("Security review: no issues found")
        else:
            typer.echo(f"Security review: {len(sec.findings)} finding(s)")
            for f in sec.findings:
                typer.echo(_safe(f"  - [{f.severity}] {f.file}: {f.issue}"))
    if report.dry_run and report.diff:
        typer.echo("")
        typer.echo(_safe(report.diff))
    elif not report.dry_run:
        typer.echo("See DEV_SUMMARY.md and DEV_GRAPH.md on the branch for details.")


@app.command()
def develop(
    path: Path = typer.Argument(..., help="Path to the backend project/repo."),
    objective: str = typer.Argument(
        ..., help='What to build, e.g. "Add JWT authentication to the API".'
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview the changes; write nothing to disk."
    ),
    max_retries: int = typer.Option(3, "--max-retries", help="Coder retries per step."),
    target_version: str = typer.Option(
        None, "--target-version", help="Target Python, e.g. py311 (default: this interpreter)."
    ),
    lang: str = typer.Option(
        "auto", "--lang",
        help="Source language: auto | python | php (auto-detects from the repo's "
        "manifest when 'auto').",
    ),
    init: bool = typer.Option(
        False, "--init", help="If PATH is not a git repo, create a baseline commit first."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the cost-confirmation prompt."
    ),
    use_subscription: bool = typer.Option(
        False,
        "--use-subscription",
        help="Use your Claude subscription login (Claude Code / `ant auth login`) "
        "instead of ANTHROPIC_API_KEY.",
    ),
    provider: str = typer.Option(
        "anthropic",
        "--provider",
        help="LLM backend: " + " | ".join(SUPPORTED_PROVIDERS) + ".",
    ),
    local: bool = typer.Option(
        False,
        "--local",
        help="Run fully offline against local Ollama (implies --provider ollama; "
        "air-gapped, no external calls). See docs/install/local_ai.md.",
    ),
    ollama_base_url: str = typer.Option(
        None,
        "--ollama-base-url",
        help="Ollama OpenAI-compatible endpoint (default http://localhost:11434/v1; "
        "or set OLLAMA_BASE_URL).",
    ),
    model: str = typer.Option(
        None,
        "--model",
        help="Default model id (required for non-anthropic providers; see "
        "docs/providers.md / docs/install/local_ai.md).",
    ),
    planner_model: str = typer.Option(
        None, "--planner-model", help="Override the model used by the Planner agent."
    ),
    coder_model: str = typer.Option(
        None, "--coder-model", help="Override the model used by the Coder agent."
    ),
    verifier_model: str = typer.Option(
        None, "--verifier-model",
        help="Model for the optional --security-review pass (the 'deep' model).",
    ),
    security_gate: bool = typer.Option(
        True, "--security-gate/--no-security-gate",
        help="Per-step blocking security gate (bandit SAST + Red Team LLM audit) on "
        "the Coder's new code; unfixable vulns are discarded. On by default; pass "
        "--no-security-gate to disable.",
    ),
    security_review: bool = typer.Option(
        False, "--security-review",
        help="Run an extra advisory LLM security review of the changed files "
        "(routed to --verifier-model). Off by default.",
    ),
    api_key: str = typer.Option(
        None, "--api-key", help="API key for the provider (else read from its env var)."
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Verbose DEBUG logging to stderr."
    ),
    quiet: bool = typer.Option(
        False, "--quiet", "-q",
        help="Suppress live progress; still print the summary and cost.",
    ),
    json_out: bool = typer.Option(
        False, "--json",
        help="Print the run report as JSON to stdout (implies --quiet).",
    ),
    report_json: Path = typer.Option(
        None, "--report-json", metavar="PATH",
        help="Also write the JSON run report to PATH.",
    ),
    no_cost: bool = typer.Option(
        False, "--no-cost", help="Do not print the final token/cost line."
    ),
) -> None:
    """Develop a backend feature on a new git branch (Planner/Coder/Verifier)."""
    if verbose and quiet:
        raise typer.BadParameter("--verbose and --quiet are mutually exclusive")
    if json_out:
        quiet = True
    # Headless CI: never block on the cost prompt (progress is suppressed below via
    # the reporter). The logging level still follows -v/-q so CI logs stay useful.
    if _is_ci():
        yes = True
    _configure_logging(verbose, quiet)

    # CLAUDEBACKEND_LOCAL=1 (e.g. inside the air-gapped Docker network) forces
    # offline mode even without --local.
    if not local and os.environ.get("CLAUDEBACKEND_LOCAL", "").strip().lower() in {
        "1", "true", "yes",
    }:
        local = True
    if local and provider == "anthropic":
        provider = "ollama"  # --local defaults the backend to local Ollama

    # Resolve the language driver: 'auto' detects from the repo, else validate early.
    from claudebackend.core.drivers import detect_lang, get_driver

    if lang == "auto":
        lang = detect_lang(path)
    else:
        try:
            get_driver(lang)
        except ValueError as exc:
            raise typer.BadParameter(str(exc))

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

    reporter = _ConsoleReporter(quiet=quiet or _is_ci())
    try:
        report = develop_feature(
            path,
            client=Client(
                use_subscription=use_subscription,
                provider=provider,
                model=primary_model,
                api_key=api_key,
                local=local,
                base_url=ollama_base_url,
            ),
            objective=objective,
            target_version=target_version,
            max_retries=max_retries,
            dry_run=dry_run,
            init=init,
            assume_yes=yes,
            cost_confirm=lambda est: typer.confirm(
                f"Estimated ~{est} input tokens for this run. Proceed?"
            ),
            on_event=reporter,
            planner_model=models_cfg["planner"],
            coder_model=models_cfg["coder"],
            verifier_model=models_cfg["verifier"],
            max_context_tokens=max_context_tokens,
            security_review=security_review,
            security_gate=security_gate,
            lang=lang,
        )
    except (OrchestratorError, GitError, SubscriptionAuthError, ProviderConfigError) as exc:
        if json_out:
            typer.echo(json.dumps(
                {"schema_version": 2, "ok": False, "error": _safe(str(exc))}
            ))
            raise typer.Exit(1)
        typer.secho(_safe(str(exc)), fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if report_json is not None:
        report_json.write_text(
            json.dumps(report.to_dict(), indent=2), encoding="utf-8"
        )

    if json_out:
        typer.echo(json.dumps(report.to_dict(), indent=2))
        return

    _print_report(report)
    if not no_cost:
        line = _cost_line(report)
        if line is not None:
            typer.echo(_safe(line))


@app.command()
def watch(
    path: Path = typer.Argument(
        Path("."), help="Project root to develop against (default: current dir)."
    ),
    test_dir: str = typer.Option(
        "tests", "--dir", help="Directory to watch for test-file saves."
    ),
    max_retries: int = typer.Option(
        3, "--max-retries", help="Coder retries per failing test before halting."
    ),
) -> None:
    """Watch a test dir; when a saved test fails, implement code to make it pass.

    Writes IN PLACE (no branch, no commit) for a fast red->green TDD loop — you
    review and commit. If a test stays red after --max-retries the watcher halts
    and waits for your next edit (it never loops).
    """
    _configure_logging(verbose=False, quiet=False)
    logging.getLogger("claudebackend").setLevel(logging.INFO)
    from claudebackend import watcher

    try:
        watcher.watch(path, test_dir, max_retries=max_retries)
    except RuntimeError as exc:
        typer.secho(_safe(str(exc)), fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


@app.command()
def ci() -> None:
    """Run the CI/CD issue->PR flow from the GitHub Actions environment.

    Reads the labeled issue from GITHUB_EVENT_PATH, develops it on an isolated
    ``claudebackend/issue-<id>`` branch, then opens a PR if it verifies safely, or
    comments on the issue explaining why it could not. Tokens come from the
    standard GitHub Actions secrets (GITHUB_TOKEN / ANTHROPIC_API_KEY).
    """
    _configure_logging(verbose=True, quiet=False)
    from claudebackend import cicd

    try:
        result = cicd.run_from_github_env()
    except (cicd.CICDError, OrchestratorError, GitError, GitHubError) as exc:
        typer.secho(_safe(str(exc)), fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    typer.echo(json.dumps(result, indent=2))


@app.command()
def mcp() -> None:
    """Run ClaudeBackend as an MCP server (stdio) for IDE/agent integration."""
    from claudebackend.mcp_server import run

    run()


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address (loopback only unless --allow-remote)."),
    port: int = typer.Option(8765, "--port", help="Port to listen on."),
    ui_dir: Path = typer.Option(
        None, "--ui-dir", help="Serve a pre-built React bundle (ui/dist) at / for single-process use."
    ),
    allow_remote: bool = typer.Option(
        False, "--allow-remote",
        help="Allow binding a non-loopback host (off by default; the dashboard is air-gapped).",
    ),
    cors_origin: list[str] = typer.Option(
        None, "--cors-origin",
        help="Allowed CORS origin (repeatable), e.g. http://127.0.0.1:5173 for the Vite dev server.",
    ),
) -> None:
    """Run the local air-gapped dashboard server (needs the [web] extra).

    Streams live pipeline events, token/cost, the dependency graph, diffs, and a
    human-in-the-loop review endpoint over loopback. The React UI in ui/ is built and
    served separately (or mount a pre-built bundle with --ui-dir); it is never packaged
    into this wheel.
    """
    from claudebackend.web import run_server

    try:
        run_server(
            host=host, port=port, allow_remote=allow_remote,
            ui_dir=str(ui_dir) if ui_dir else None,
            cors_origins=cors_origin or [],
        )
    except RuntimeError as exc:
        typer.secho(_safe(str(exc)), fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


def main() -> None:
    """Console-script entry point (`claudebackend`)."""
    app()


if __name__ == "__main__":
    main()
