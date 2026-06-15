"""Minimal GitHub REST client (stdlib only) for the CI/CD flow.

Used only in CI to open a pull request or comment on an issue, so there is no
third-party dependency: requests go through ``urllib``. The auth token and the
``owner/repo`` are read from the environment by the caller (never hardcoded), in
keeping with GitHub Actions secret injection.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

API_ROOT = "https://api.github.com"


class GitHubError(RuntimeError):
    """A GitHub REST call failed."""


def _post(url: str, payload: dict, token: str) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "claudebackend")
    try:
        with urllib.request.urlopen(req) as resp:  # noqa: S310 - fixed https API host
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise GitHubError(f"GitHub API {exc.code} for {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise GitHubError(f"GitHub API request failed for {url}: {exc}") from exc


def create_pull_request(repo: str, head: str, base: str, title: str, body: str,
                        token: str) -> dict:
    """Open a PR (``repo`` is ``"owner/name"``). Returns the PR JSON (incl. ``html_url``)."""
    url = f"{API_ROOT}/repos/{repo}/pulls"
    return _post(url, {"title": title, "head": head, "base": base, "body": body}, token)


def comment_on_issue(repo: str, issue_number: int, body: str, token: str) -> dict:
    """Add a comment to an issue/PR thread."""
    url = f"{API_ROOT}/repos/{repo}/issues/{issue_number}/comments"
    return _post(url, {"body": body}, token)


def env_repo() -> str | None:
    """The ``owner/name`` slug GitHub Actions exposes as ``GITHUB_REPOSITORY``."""
    return os.environ.get("GITHUB_REPOSITORY") or None


def env_token() -> str | None:
    """The token injected as ``GITHUB_TOKEN`` (or ``GH_TOKEN``)."""
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or None
