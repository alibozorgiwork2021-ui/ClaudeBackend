import pytest

import claudebackend.core.git as git_mod
from claudebackend.core.git import (
    GitError,
    commit_module,
    count_commits,
    create_branch,
    current_branch,
    init_baseline,
    is_repo,
    push_branch,
    require_clean_tree,
    write_summary,
)


def _plain(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    return tmp_path


def test_is_repo_false_then_true(tmp_path):
    _plain(tmp_path)
    assert is_repo(tmp_path) is False
    init_baseline(tmp_path)
    assert is_repo(tmp_path) is True


def test_init_baseline_commits_files_and_is_clean(tmp_path):
    _plain(tmp_path)
    init_baseline(tmp_path)
    assert count_commits(tmp_path) == 1
    require_clean_tree(tmp_path)  # must not raise


def test_require_clean_tree_aborts_when_dirty(tmp_path):
    _plain(tmp_path)
    init_baseline(tmp_path)
    (tmp_path / "a.py").write_text("x = 2\n", encoding="utf-8")
    with pytest.raises(GitError):
        require_clean_tree(tmp_path)


def test_create_branch(tmp_path):
    _plain(tmp_path)
    init_baseline(tmp_path)
    create_branch(tmp_path, "claudebackend/feature-test")
    assert current_branch(tmp_path) == "claudebackend/feature-test"


def test_commit_module_adds_one_commit(tmp_path):
    _plain(tmp_path)
    init_baseline(tmp_path)
    create_branch(tmp_path, "wip")
    before = count_commits(tmp_path)
    (tmp_path / "a.py").write_text("x = 3\n", encoding="utf-8")
    commit_module(tmp_path, ["a.py"], "ClaudeBackend: modify a.py")
    assert count_commits(tmp_path) == before + 1
    require_clean_tree(tmp_path)


def test_branch_name_uses_feature_prefix():
    from claudebackend.core.git import branch_name

    assert branch_name().startswith("claudebackend/feature-")


def test_write_summary_creates_and_commits(tmp_path):
    _plain(tmp_path)
    init_baseline(tmp_path)
    write_summary(tmp_path, "# Summary\n")
    assert (tmp_path / "DEV_SUMMARY.md").read_text(encoding="utf-8") == "# Summary\n"
    require_clean_tree(tmp_path)


@pytest.mark.parametrize("protected", ["main", "master"])
def test_push_branch_refuses_protected(protected):
    with pytest.raises(GitError):
        push_branch("/repo", protected)


def test_push_branch_invokes_git_push(monkeypatch):
    calls = []
    monkeypatch.setattr(git_mod, "_git", lambda root, *args, **kw: calls.append(args) or (0, ""))
    push_branch("/repo", "claudebackend/issue-1")
    assert calls == [("push", "-u", "origin", "claudebackend/issue-1")]
