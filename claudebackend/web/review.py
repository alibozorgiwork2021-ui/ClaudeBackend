"""Human-in-the-loop review: approve (keep) or reject (revert) flagged changes.

A reject reverts the file to its pre-run baseline and commits the revert ON THE
FEATURE BRANCH — never on ``main``/``master`` (enforced in ``git.revert_path_on_branch``).
Review is only meaningful for a live run; a dry run wrote nothing to revert.
"""

from __future__ import annotations

from claudebackend.core import git


class ReviewError(RuntimeError):
    """A review request could not be applied (e.g. against a dry run)."""


def _validate_relpath(path: str) -> None:
    """Reject anything that is not a repo-relative file: a leading-slash absolute
    (``/etc/passwd``), a Windows drive (``C:\\...``), or any ``..`` traversal — the
    decision path is handed to git as a pathspec, so it must stay inside the repo."""
    norm = str(path).replace("\\", "/")
    segments = norm.split("/")
    if (
        norm.startswith("/")
        or (len(norm) >= 2 and norm[1] == ":")
        or ".." in segments
    ):
        raise ReviewError(f"review path must be a repo-relative file, got {path!r}")


def apply_review(handle, decisions: list[dict]) -> dict:
    """Apply ``[{"path": ..., "decision": "approve"|"reject"}, ...]`` to a live run.

    Returns a confirmation dict including which paths were reverted/kept, the branch
    the effects landed on, and ``main_untouched`` (always true — the revert refuses a
    protected branch).
    """
    if handle.dry_run:
        raise ReviewError("review is only available for a live (non-dry-run) run")
    if handle.status == "running":
        raise ReviewError("run is still in progress; wait for it to finish before reviewing")
    if handle.baseline_sha is None:
        raise ReviewError("no revert baseline was captured for this run")

    reverted: list[str] = []
    kept: list[str] = []
    for d in decisions:
        path = d.get("path")
        if not path:
            continue
        _validate_relpath(path)
        if d.get("decision") == "reject":
            if git.revert_path_on_branch(handle.root, path, handle.baseline_sha):
                reverted.append(path)
        else:
            kept.append(path)

    branch = git.current_branch(handle.root)
    return {
        "reverted": reverted,
        "kept": kept,
        "branch": branch,
        "main_untouched": branch not in ("main", "master"),
    }
