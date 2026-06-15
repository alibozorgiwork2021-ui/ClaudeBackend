"""Tests for claudebackend.core.events — typed pipeline progress events."""

from __future__ import annotations

import dataclasses

import pytest

from claudebackend.core.events import (
    Commit,
    DepGraphDone,
    Event,
    FileDone,
    FileRetry,
    PlanDone,
    ProjectVerifyResult,
    SecurityReject,
    StepStart,
)


# ---------------------------------------------------------------------------
# DepGraphDone
# ---------------------------------------------------------------------------


def test_depgraphdone_fields_round_trip():
    e = DepGraphDone(files=37, dynamic=2, kinds={"python": 30, "config": 7})
    assert e.files == 37
    assert e.dynamic == 2
    assert e.kinds == {"python": 30, "config": 7}


def test_depgraphdone_kinds_defaults_empty():
    e = DepGraphDone(files=1, dynamic=0)
    assert e.kinds == {}


def test_depgraphdone_frozen():
    e = DepGraphDone(files=1, dynamic=0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.files = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PlanDone
# ---------------------------------------------------------------------------


def test_plandone_fields_round_trip():
    e = PlanDone(steps=10, high_risk=3)
    assert e.steps == 10
    assert e.high_risk == 3


def test_plandone_frozen():
    e = PlanDone(steps=5, high_risk=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.steps = 0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# StepStart
# ---------------------------------------------------------------------------


def test_stepstart_fields_round_trip():
    e = StepStart(index=2, total=10, path="src/a.py", action="modify")
    assert e.index == 2
    assert e.total == 10
    assert e.path == "src/a.py"
    assert e.action == "modify"


def test_stepstart_frozen():
    e = StepStart(index=1, total=5, path="x.py", action="create")
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.index = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# FileRetry
# ---------------------------------------------------------------------------


def test_fileretry_fields_round_trip():
    e = FileRetry(path="src/foo.py", attempt=1)
    assert e.path == "src/foo.py"
    assert e.attempt == 1


def test_fileretry_frozen():
    e = FileRetry(path="y.py", attempt=2)
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.attempt = 5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# FileDone
# ---------------------------------------------------------------------------


def test_filedone_ok_true():
    e = FileDone(path="src/ok.py", ok=True)
    assert e.path == "src/ok.py"
    assert e.ok is True


def test_filedone_ok_false():
    e = FileDone(path="src/flagged.py", ok=False)
    assert e.ok is False


def test_filedone_frozen():
    e = FileDone(path="z.py", ok=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.ok = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SecurityReject
# ---------------------------------------------------------------------------


def test_securityreject_fields_round_trip():
    e = SecurityReject(path="api.py", attempt=2, issues=("[high] SQLi",))
    assert e.path == "api.py"
    assert e.attempt == 2
    assert e.issues == ("[high] SQLi",)


def test_securityreject_frozen():
    e = SecurityReject(path="api.py", attempt=1, issues=())
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.attempt = 9  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ProjectVerifyResult
# ---------------------------------------------------------------------------


def test_projectverifyresult_fields_round_trip():
    steps = {"compile": "ok", "ruff": "ok", "pytest": "18 passed"}
    e = ProjectVerifyResult(steps=steps, ok=True)
    assert e.steps == {"compile": "ok", "ruff": "ok", "pytest": "18 passed"}
    assert e.ok is True


def test_projectverifyresult_ok_false():
    steps = {"compile": "2 errors", "ruff": "ok"}
    e = ProjectVerifyResult(steps=steps, ok=False)
    assert e.ok is False
    assert e.steps["compile"] == "2 errors"


def test_projectverifyresult_frozen_attribute():
    e = ProjectVerifyResult(steps={"a": "ok"}, ok=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.ok = False  # type: ignore[misc]


def test_projectverifyresult_dict_field_is_mutable():
    # frozen=True blocks attribute rebinding, not mutation of the dict value
    steps: dict[str, str] = {}
    e = ProjectVerifyResult(steps=steps, ok=True)
    e.steps["new_step"] = "ok"  # mutable dict — this is intentional by design
    assert e.steps["new_step"] == "ok"


# ---------------------------------------------------------------------------
# Commit
# ---------------------------------------------------------------------------


def test_commit_fields_round_trip():
    e = Commit(paths=("src/a.py", "src/b.py"))
    assert e.paths == ("src/a.py", "src/b.py")


def test_commit_frozen():
    e = Commit(paths=("x.py",))
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.paths = ("y.py",)  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Event union — all concrete types are accepted where Event is expected
# ---------------------------------------------------------------------------


def _accepts_event(e: Event) -> type:
    """Dummy function annotated with Event to check runtime usability."""
    return type(e)


def test_event_union_members():
    samples = [
        DepGraphDone(files=1, dynamic=0),
        PlanDone(steps=3, high_risk=1),
        StepStart(index=0, total=1, path="f.py", action="create"),
        FileRetry(path="f.py", attempt=1),
        SecurityReject(path="f.py", attempt=1, issues=("[high] x",)),
        FileDone(path="f.py", ok=True),
        ProjectVerifyResult(steps={"compile": "ok"}, ok=True),
        Commit(paths=("f.py",)),
    ]
    for e in samples:
        assert _accepts_event(e) is type(e)
