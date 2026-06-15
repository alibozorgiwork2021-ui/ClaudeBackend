import io
import json
import urllib.error

import pytest

from claudebackend.core import github
from claudebackend.core.github import GitHubError


class _FakeResp:
    def __init__(self, payload):
        self._data = json.dumps(payload).encode()

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch_urlopen(monkeypatch, captured, payload):
    def fake_urlopen(req):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["headers"] = {k.lower(): v for k, v in req.header_items()}
        captured["body"] = json.loads(req.data.decode())
        return _FakeResp(payload)

    monkeypatch.setattr(github.urllib.request, "urlopen", fake_urlopen)


def test_create_pull_request_posts_correctly(monkeypatch):
    captured = {}
    _patch_urlopen(monkeypatch, captured, {"html_url": "https://github.com/o/r/pull/7"})

    out = github.create_pull_request(
        "o/r", head="claudebackend/issue-1", base="main",
        title="T", body="B", token="tok",
    )

    assert out["html_url"].endswith("/pull/7")
    assert captured["url"] == "https://api.github.com/repos/o/r/pulls"
    assert captured["method"] == "POST"
    assert captured["body"] == {
        "title": "T", "head": "claudebackend/issue-1", "base": "main", "body": "B",
    }
    assert captured["headers"]["authorization"] == "Bearer tok"


def test_comment_on_issue_posts_correctly(monkeypatch):
    captured = {}
    _patch_urlopen(monkeypatch, captured, {"id": 1})

    github.comment_on_issue("o/r", 42, "hi", "tok")

    assert captured["url"] == "https://api.github.com/repos/o/r/issues/42/comments"
    assert captured["body"] == {"body": "hi"}


def test_http_error_becomes_githuberror(monkeypatch):
    def fake_urlopen(req):
        raise urllib.error.HTTPError(
            req.full_url, 422, "Unprocessable", {}, io.BytesIO(b'{"message":"bad"}')
        )

    monkeypatch.setattr(github.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(GitHubError):
        github.comment_on_issue("o/r", 1, "b", "tok")


def test_env_helpers(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    assert github.env_repo() == "o/r"
    assert github.env_token() == "tok"
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert github.env_repo() is None
    assert github.env_token() is None
