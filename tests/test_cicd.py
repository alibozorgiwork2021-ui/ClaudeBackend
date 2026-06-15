import json

import pytest

from claudebackend import cicd
from claudebackend.orchestrator import DevReport


def _report(*, project_ok, unsafe=None):
    r = DevReport(objective="o", project_ok=project_ok, branch="claudebackend/issue-5")
    r.unsafe = unsafe or []
    r.summary = "SUMMARY BODY"
    r.verify_steps = {"compile": "ok", "pytest": "1 passed" if project_ok else "FAILED"}
    return r


def _patch(monkeypatch, report):
    calls = {"push": [], "pr": [], "comment": []}
    monkeypatch.setattr(cicd, "develop_feature", lambda *a, **k: report)
    monkeypatch.setattr(cicd.git, "push_branch",
                        lambda root, branch: calls["push"].append(branch))
    monkeypatch.setattr(
        cicd.github, "create_pull_request",
        lambda repo, head, base, title, body, token: (
            calls["pr"].append((repo, head, base, body)) or {"html_url": "URL"}
        ),
    )
    monkeypatch.setattr(cicd.github, "comment_on_issue",
                        lambda repo, n, body, token: calls["comment"].append((repo, n)))
    return calls


def test_safe_run_pushes_and_opens_pr(monkeypatch):
    calls = _patch(monkeypatch, _report(project_ok=True))

    out = cicd.run_issue("/root", 5, "Add X", "body", repo="o/r", token="t",
                         client=object())

    assert out["action"] == "pr"
    assert out["branch"] == "claudebackend/issue-5"
    assert out["url"] == "URL"
    assert calls["push"] == ["claudebackend/issue-5"]
    assert calls["pr"] and calls["pr"][0][1] == "claudebackend/issue-5"
    assert "SUMMARY BODY" in calls["pr"][0][3]  # DEV_SUMMARY in PR body
    assert not calls["comment"]


def test_failed_verify_comments_and_opens_no_pr(monkeypatch):
    calls = _patch(monkeypatch, _report(project_ok=False))

    out = cicd.run_issue("/root", 5, "Add X", "body", repo="o/r", token="t",
                         client=object())

    assert out["action"] == "comment"
    assert calls["comment"] and not calls["pr"] and not calls["push"]


def test_unsafe_files_block_pr(monkeypatch):
    calls = _patch(monkeypatch, _report(project_ok=True, unsafe=["danger.py"]))

    out = cicd.run_issue("/root", 5, "Add X", "body", repo="o/r", token="t",
                         client=object())

    assert out["action"] == "comment"
    assert not calls["pr"] and not calls["push"]


def test_run_from_github_env_missing_raises(monkeypatch):
    for v in ("GITHUB_REPOSITORY", "GITHUB_TOKEN", "GH_TOKEN", "GITHUB_EVENT_PATH"):
        monkeypatch.delenv(v, raising=False)
    with pytest.raises(cicd.CICDError):
        cicd.run_from_github_env()


def test_run_from_github_env_parses_event(monkeypatch, tmp_path):
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps({"issue": {"number": 9, "title": "T", "body": "B"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
    seen = {}

    def fake_run_issue(root, number, title, body, *, repo, token, base):
        seen.update(root=root, number=number, title=title, repo=repo,
                    token=token, base=base)
        return {"action": "pr"}

    monkeypatch.setattr(cicd, "run_issue", fake_run_issue)

    out = cicd.run_from_github_env()

    assert out == {"action": "pr"}
    assert seen["number"] == 9
    assert seen["repo"] == "o/r"
    assert seen["base"] == "main"  # default when no base/ref env
