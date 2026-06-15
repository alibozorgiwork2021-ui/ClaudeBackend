"""Git integration: clean-tree guard, baseline-on-init, branch, commits.

Safety model: never touch a dirty working tree (the caller must abort first);
operate on a new branch off HEAD; refuse a non-repo unless the caller opts into
``init_baseline`` (which commits the current tree so the work is diffable).
Commits use a fixed ClaudeBackend identity, injected per command so the user's
git config is never mutated.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

_IDENT = ["-c", "user.email=claudebackend@local", "-c", "user.name=ClaudeBackend"]


class GitError(RuntimeError):
    """A git command failed or the working tree is in an unexpected state."""


def _git(root, *args: str, check: bool = True) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed:\n{out.strip()}")
    return proc.returncode, out


def is_repo(root) -> bool:
    rc, _ = _git(root, "rev-parse", "--is-inside-work-tree", check=False)
    return rc == 0


def require_clean_tree(root) -> None:
    """Raise if the working tree has uncommitted changes (a non-repo is clean)."""
    if not is_repo(root):
        return
    _, out = _git(root, "status", "--porcelain")
    if out.strip():
        raise GitError(
            "working tree is not clean; commit or stash changes before starting:\n"
            + out.strip()
        )


def init_baseline(
    root, message: str = "ClaudeBackend baseline"
) -> None:
    """Initialise a repo and commit the current tree as the baseline."""
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, *_IDENT, "commit", "-q", "-m", message)


def branch_name(prefix: str = "claudebackend/feature") -> str:
    return f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}"


def create_branch(root, name: str) -> None:
    _git(root, "checkout", "-q", "-b", name)


def current_branch(root) -> str:
    _, out = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    return out.strip()


def push_branch(root, branch: str, remote: str = "origin") -> None:
    """Push ``branch`` to ``remote`` and set upstream.

    Safety: refuses to push ``main``/``master`` — automated changes must always
    land on an isolated feature branch. Credentials are whatever the environment
    already provides (e.g. GitHub Actions' ``actions/checkout`` configures the
    remote with a token); this never reads or writes a token itself.
    """
    if branch in ("main", "master"):
        raise GitError(f"refusing to push protected branch '{branch}'")
    _git(root, "push", "-u", remote, branch)


def commit_module(root, paths, message: str) -> None:
    """Stage the given repo-relative paths and create one commit.

    Staging uses ``-A`` so deletions are recorded too. If nothing actually
    changed for these paths (e.g. the Coder reproduced an identical file), there
    is nothing to commit and we return without creating an empty commit.
    """
    specs = [str(p) for p in paths]
    _git(root, "add", "-A", "--", *specs)
    rc, _ = _git(root, "diff", "--cached", "--quiet", "--", *specs, check=False)
    if rc == 0:
        return  # no staged changes for these paths
    _git(root, *_IDENT, "commit", "-q", "-m", message)


def count_commits(root) -> int:
    _, out = _git(root, "rev-list", "--count", "HEAD")
    return int(out.strip() or "0")


def diff(root) -> str:
    """Unified diff of unstaged working-tree changes."""
    _, out = _git(root, "diff", check=False)
    return out


def diff_all(root) -> str:
    """Unified diff of all changes, including new and deleted files.

    Stages everything first so ``--dry-run`` previews include created/deleted
    files (a plain ``git diff`` omits untracked ones). Safe on the throwaway
    copy used for dry runs.
    """
    _git(root, "add", "-A")
    _, out = _git(root, "diff", "--cached", check=False)
    return out


def head_sha(root) -> str:
    """The current HEAD commit sha (used as a revert baseline)."""
    _, out = _git(root, "rev-parse", "HEAD")
    return out.strip()


def show_commit_diff(root, paths=None) -> str:
    """Unified diff introduced by the HEAD commit (optionally limited to paths).

    Read-only — used to stream a live run's per-commit diff to the dashboard as
    commits land. ``--format=`` suppresses the commit header so only the patch is
    returned.
    """
    args = ["show", "--format=", "HEAD"]
    if paths:
        args += ["--", *[str(p) for p in paths]]
    _, out = _git(root, *args, check=False)
    return out


def revert_path_on_branch(root, path, baseline_sha: str) -> bool:
    """Restore ``path`` to its state at ``baseline_sha`` and commit the revert ON
    THE CURRENT (feature) branch. Returns True if a revert commit was made.

    Refuses to touch ``main``/``master`` — a dashboard "reject" must never alter a
    protected branch (the git-safety model). If ``path`` did not exist at the
    baseline it is removed; if nothing actually changed, no commit is made.
    """
    branch = current_branch(root)
    if branch in ("main", "master"):
        raise GitError(f"refusing to modify protected branch '{branch}'")
    spec = str(path)
    rc, _ = _git(root, "cat-file", "-e", f"{baseline_sha}:{spec}", check=False)
    if rc == 0:
        _git(root, "checkout", baseline_sha, "--", spec)
    else:
        _git(root, "rm", "-q", "-f", "--", spec, check=False)
    _git(root, "add", "-A", "--", spec)
    rc2, _ = _git(root, "diff", "--cached", "--quiet", "--", spec, check=False)
    if rc2 == 0:
        return False  # nothing to revert
    _git(root, *_IDENT, "commit", "-q", "-m", f"ClaudeBackend: revert {spec} (review reject)")
    return True


def write_summary(
    root, content: str, message: str = "ClaudeBackend dev summary"
) -> None:
    (Path(root) / "DEV_SUMMARY.md").write_text(content, encoding="utf-8")
    _git(root, "add", "--", "DEV_SUMMARY.md")
    _git(root, *_IDENT, "commit", "-q", "-m", message)
