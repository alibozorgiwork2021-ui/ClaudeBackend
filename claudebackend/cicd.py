"""CI/CD: turn a labeled GitHub issue into a branch + pull request.

Invoked by ``claudebackend ci`` inside a GitHub Action. It develops the issue on an
isolated ``claudebackend/issue-<id>`` branch and then EITHER pushes the branch and
opens a PR (only when the run verified safely) OR comments on the issue explaining
why it could not — it never opens a PR for a failed/unsafe run, and never pushes to
``main``/``master`` (guarded in ``git.push_branch``).

Tokens and the repo slug are read from the environment (standard GitHub Actions
secret injection); nothing is hardcoded.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from claudebackend.core import git, github
from claudebackend.core.client import Client
from claudebackend.orchestrator import develop_feature

logger = logging.getLogger(__name__)


class CICDError(RuntimeError):
    """The CI/CD flow could not run (missing event payload / token / repo)."""


def _cost_summary(report) -> str:
    if report.cost is None:
        return "Cost: n/a"
    u = report.cost.usage
    usd = f" ~${report.cost.cost_usd:.2f}" if report.cost.pricing_known else " (cost unknown)"
    return (
        f"Cost: in {u.input_tokens} / out {u.output_tokens} tokens, "
        f"{u.calls} calls{usd}"
    )


def build_pr_body(report, issue_number) -> str:
    """The PR body: DEV_SUMMARY + cost/tokens + verify steps + review/unsafe flags."""
    steps = ", ".join(f"{k}={v}" for k, v in report.verify_steps.items())
    lines = [
        f"Automated by ClaudeBackend for #{issue_number}.",
        "",
        _cost_summary(report),
        f"Verification: {'PASSED' if report.project_ok else 'FAILED'} ({steps})",
    ]
    if report.review:
        lines += ["", "**Needs human review (CLAUDEBACKEND-REVIEW markers):**"]
        lines += [f"- {p}" for p in report.review]
    if report.security_issues:
        lines += ["", f"**SAST findings (advisory): {len(report.security_issues)}**"]
    if report.unsafe:
        lines += ["", "**Discarded by the security gate (not included):**"]
        lines += [f"- {p}" for p in report.unsafe]
    lines += ["", "---", "", report.summary]
    return "\n".join(lines)


def _failure_comment(report) -> str:
    parts = [
        "ClaudeBackend could not safely implement this issue, so **no pull request "
        "was opened**.",
        "",
        f"Verification: {'PASSED' if report.project_ok else 'FAILED'}.",
    ]
    if report.unsafe:
        parts += ["", "Files the security gate discarded as unsafe:"]
        parts += [f"- {p}" for p in report.unsafe]
    if report.project_errors:
        joined = "\n".join(report.project_errors)
        parts += [
            "",
            "<details><summary>Verification errors</summary>",
            "",
            "```",
            joined,
            "```",
            "</details>",
        ]
    parts += ["", "Edit the issue or the code and re-apply the label to try again."]
    return "\n".join(parts)


def run_issue(root, issue_number, title, body, *, repo, token, base="main",
              client=None, on_event=None) -> dict:
    """Develop ``issue_number`` and open a PR (safe) or comment (unsafe/failed).

    Returns ``{"action": "pr", "url", "branch", ...}`` or
    ``{"action": "comment", ...}``.
    """
    objective = f"{title}\n\n{body}".strip()
    branch = f"claudebackend/issue-{issue_number}"
    report = develop_feature(
        Path(root),
        client=client or Client(),
        objective=objective,
        branch_name=branch,
        assume_yes=True,
        security_gate=True,
        security_review=True,
        on_event=on_event,
    )

    # Open a PR ONLY when the deterministic verify passed AND nothing was discarded
    # as unsafe by the Red Team gate. Otherwise explain on the issue.
    if report.project_ok and not report.unsafe:
        git.push_branch(root, branch)
        pr = github.create_pull_request(
            repo,
            head=branch,
            base=base,
            title=f"ClaudeBackend: {title}".strip() or f"ClaudeBackend: issue #{issue_number}",
            body=build_pr_body(report, issue_number),
            token=token,
        )
        logger.info("opened PR %s", pr.get("html_url"))
        return {
            "action": "pr",
            "branch": branch,
            "url": pr.get("html_url"),
            "project_ok": report.project_ok,
        }

    github.comment_on_issue(repo, issue_number, _failure_comment(report), token)
    logger.info("commented on issue #%s (no PR: project_ok=%s, unsafe=%s)",
                issue_number, report.project_ok, report.unsafe)
    return {
        "action": "comment",
        "project_ok": report.project_ok,
        "unsafe": report.unsafe,
    }


def run_from_github_env() -> dict:
    """Read the GitHub Actions environment (issue event + token + repo) and run."""
    repo = github.env_repo()
    token = github.env_token()
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not (repo and token and event_path and Path(event_path).exists()):
        raise CICDError(
            "missing GitHub Actions environment: need GITHUB_REPOSITORY, GITHUB_TOKEN, "
            "and GITHUB_EVENT_PATH pointing at the issue event payload."
        )
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    issue = event.get("issue") or {}
    number = issue.get("number")
    if number is None:
        raise CICDError("event payload has no issue.number (not an issue event?)")
    base = os.environ.get("GITHUB_BASE_REF") or os.environ.get("GITHUB_REF_NAME") or "main"
    root = os.environ.get("GITHUB_WORKSPACE") or "."
    return run_issue(
        root, number, issue.get("title") or "", issue.get("body") or "",
        repo=repo, token=token, base=base,
    )
