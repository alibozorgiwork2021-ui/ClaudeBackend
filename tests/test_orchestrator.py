import pytest

from claudebackend.core import events, git
from claudebackend.core.pricing import CostReport, Usage
from claudebackend.core.verifier import SastFinding
from claudebackend.models import (
    ExecutionPlan,
    PlanStep,
    SecurityFinding,
    SecurityReview,
)
from claudebackend.orchestrator import OrchestratorError, develop_feature


class FakeClient:
    """Returns a fixed ExecutionPlan and maps each target file to canned code.

    ``parse`` is type-aware: it returns the plan for an ``ExecutionPlan`` request
    and a ``SecurityReview`` for the per-step Red Team audit. ``security`` may be a
    single ``SecurityReview`` (returned every audit) or a list returned in order
    (the last entry repeats); ``None`` means every audit passes clean.
    """

    def __init__(self, outputs, plan=None, security=None):
        self.outputs = outputs
        self.plan = plan or ExecutionPlan(objective="obj", steps=[])
        self.security = security
        self.calls = []
        self.audit_calls = []

    def estimate_tokens(self, messages):
        return 10

    def parse(self, messages, output_model, model=None):
        if output_model is SecurityReview:
            idx = len(self.audit_calls)
            self.audit_calls.append(messages)
            if self.security is None:
                return SecurityReview(ok=True)
            if isinstance(self.security, list):
                return self.security[min(idx, len(self.security) - 1)]
            return self.security
        return self.plan

    def stream_text(self, messages, system=None, model=None):
        text = "\n".join(b["text"] for b in messages[0]["content"])
        for path, code in self.outputs.items():
            if f"=== {path} ===" in text:
                self.calls.append(path)
                return code, "end_turn"
        raise AssertionError(f"no canned output matched:\n{text}")


def _repo(tmp_path):
    (tmp_path / "a.py").write_text("VALUE = 'a'\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("from a import VALUE\n", encoding="utf-8")
    return tmp_path


PLAN = ExecutionPlan(
    objective="Modernize",
    summary="touch a then b",
    steps=[
        PlanStep(path="a.py", action="modify", instructions="modernize a"),
        PlanStep(path="b.py", action="modify", instructions="modernize b",
                 depends_on=["a.py"]),
    ],
)
GOOD = {"a.py": "VALUE = 'a'\n", "b.py": "from a import VALUE\nUSE = VALUE\n"}


def test_runs_steps_in_dependency_order_and_commits(tmp_path):
    _repo(tmp_path)
    client = FakeClient(GOOD, plan=PLAN)

    report = develop_feature(tmp_path, client=client, objective="Modernize", init=True)

    assert client.calls == ["a.py", "b.py"]  # depends_on orders a before b
    assert report.project_ok is True, report.project_errors
    assert report.objective == "Modernize"
    assert report.branch.startswith("claudebackend/feature-")
    assert git.current_branch(tmp_path) == report.branch
    assert "a.py" in report.modified and "b.py" in report.modified
    assert git.count_commits(tmp_path) >= 3  # baseline + steps + graph + summary
    git.require_clean_tree(tmp_path)  # everything committed
    assert (tmp_path / "DEV_GRAPH.md").exists()
    assert (tmp_path / "DEV_SUMMARY.md").exists()


def test_branch_name_override(tmp_path):
    _repo(tmp_path)
    report = develop_feature(
        tmp_path, client=FakeClient(GOOD, plan=PLAN), objective="o", init=True,
        branch_name="claudebackend/issue-42",
    )
    assert report.branch == "claudebackend/issue-42"
    assert git.current_branch(tmp_path) == "claudebackend/issue-42"


def test_apply_in_place_writes_without_branch_or_commit(tmp_path):
    _repo(tmp_path)
    git.init_baseline(tmp_path)
    # Dirty the tree like a developer mid-edit — in-place mode tolerates it.
    (tmp_path / "b.py").write_text("from a import VALUE\n# editing\n", encoding="utf-8")
    before_commits = git.count_commits(tmp_path)
    before_branch = git.current_branch(tmp_path)

    report = develop_feature(
        tmp_path, client=FakeClient(GOOD, plan=PLAN), objective="o",
        apply_in_place=True,
    )

    assert report.branch is None  # no branch created
    assert git.current_branch(tmp_path) == before_branch
    assert git.count_commits(tmp_path) == before_commits  # nothing committed
    assert "USE = VALUE" in (tmp_path / "b.py").read_text(encoding="utf-8")  # in place
    assert report.project_ok is True, report.project_errors


def test_create_and_delete_steps(tmp_path):
    (tmp_path / "keep.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "old.py").write_text("y = 2\n", encoding="utf-8")
    plan = ExecutionPlan(
        objective="restructure",
        steps=[
            PlanStep(path="new.py", action="create", instructions="add new"),
            PlanStep(path="old.py", action="delete", instructions="drop old"),
        ],
    )
    client = FakeClient({"new.py": "Z = 3\n"}, plan=plan)

    report = develop_feature(tmp_path, client=client, objective="restructure", init=True)

    assert "new.py" in report.created
    assert "old.py" in report.deleted
    assert (tmp_path / "new.py").exists()
    assert not (tmp_path / "old.py").exists()
    assert report.project_ok is True, report.project_errors


def test_review_markers_surface(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    plan = ExecutionPlan(
        objective="o",
        steps=[PlanStep(path="a.py", action="modify", instructions="touch")],
    )
    code = "x = 1  # CLAUDEBACKEND-REVIEW: ambiguous choice\n"
    report = develop_feature(
        tmp_path, client=FakeClient({"a.py": code}, plan=plan), objective="o", init=True
    )
    assert "a.py" in report.review


def test_retries_then_flags_on_persistent_failure(tmp_path):
    (tmp_path / "bad.py").write_text("x = 1\n", encoding="utf-8")
    plan = ExecutionPlan(
        objective="o",
        steps=[PlanStep(path="bad.py", action="modify", instructions="break it")],
    )
    client = FakeClient({"bad.py": "def (:\n"}, plan=plan)  # never compiles

    report = develop_feature(
        tmp_path, client=client, objective="o", init=True, max_retries=3
    )

    assert client.calls.count("bad.py") == 3  # retried up to max_retries
    assert "bad.py" in report.flagged
    assert report.project_ok is False


def test_refuses_non_repo_without_init(tmp_path):
    _repo(tmp_path)
    with pytest.raises(OrchestratorError):
        develop_feature(tmp_path, client=FakeClient(GOOD, plan=PLAN),
                        objective="o", init=False)


def test_aborts_on_dirty_tree(tmp_path):
    _repo(tmp_path)
    git.init_baseline(tmp_path)
    (tmp_path / "a.py").write_text("VALUE = 'dirty'\n", encoding="utf-8")
    with pytest.raises(git.GitError):
        develop_feature(tmp_path, client=FakeClient(GOOD, plan=PLAN),
                        objective="o", init=False)


def test_dry_run_writes_nothing_to_repo(tmp_path):
    _repo(tmp_path)
    git.init_baseline(tmp_path)
    before_commits = git.count_commits(tmp_path)
    before_branch = git.current_branch(tmp_path)
    before_b = (tmp_path / "b.py").read_text(encoding="utf-8")

    report = develop_feature(
        tmp_path, client=FakeClient(GOOD, plan=PLAN), objective="o", dry_run=True
    )

    assert report.dry_run is True
    assert git.count_commits(tmp_path) == before_commits  # no new commits
    assert git.current_branch(tmp_path) == before_branch  # no new branch
    assert (tmp_path / "b.py").read_text(encoding="utf-8") == before_b  # untouched
    assert "USE = VALUE" in report.diff  # preview shows the change
    assert not (tmp_path / "DEV_GRAPH.md").exists()  # nothing written to the repo


def test_cost_gate_aborts_when_declined(tmp_path):
    _repo(tmp_path)
    with pytest.raises(OrchestratorError):
        develop_feature(
            tmp_path,
            client=FakeClient(GOOD, plan=PLAN),
            objective="o",
            init=True,
            cost_warn_tokens=1,
            cost_confirm=lambda est: False,
        )


class RecordingReporter:
    def __init__(self):
        self.events = []

    def __call__(self, event):
        self.events.append(event)

    def of_type(self, cls):
        return [e for e in self.events if isinstance(e, cls)]


class CostClient(FakeClient):
    def __init__(self, outputs, plan=None, model="claude-opus-4-8"):
        super().__init__(outputs, plan)
        self.usage = Usage()
        self._model = model

    def cost_report(self):
        from claudebackend.core.pricing import price

        return price(self._model, self.usage)


def test_emits_event_sequence_on_dry_run(tmp_path):
    _repo(tmp_path)
    git.init_baseline(tmp_path)
    reporter = RecordingReporter()

    develop_feature(tmp_path, client=FakeClient(GOOD, plan=PLAN), objective="o",
                    dry_run=True, on_event=reporter)

    assert isinstance(reporter.events[0], events.DepGraphDone)
    assert isinstance(reporter.events[1], events.PlanDone)
    assert isinstance(reporter.events[-1], events.ProjectVerifyResult)

    step_starts = reporter.of_type(events.StepStart)
    total = step_starts[0].total
    assert total == 2
    assert [s.index for s in step_starts] == list(range(1, total + 1))
    assert all(s.total == total for s in step_starts)

    file_done = reporter.of_type(events.FileDone)
    assert {fd.path for fd in file_done} == {"a.py", "b.py"}
    assert all(fd.ok for fd in file_done)


def test_default_on_event_is_noop(tmp_path, capsys):
    _repo(tmp_path)

    report = develop_feature(tmp_path, client=FakeClient(GOOD, plan=PLAN),
                             objective="o", init=True)

    assert report.project_ok is True, report.project_errors
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err == ""


def test_report_cost_set_when_client_supports_it(tmp_path):
    _repo(tmp_path)
    client = CostClient(GOOD, plan=PLAN)

    report = develop_feature(tmp_path, client=client, objective="o", init=True)

    assert isinstance(report.cost, CostReport)
    assert report.cost.pricing_known is True


def test_report_cost_none_when_client_lacks_method(tmp_path):
    _repo(tmp_path)

    report = develop_feature(tmp_path, client=FakeClient(GOOD, plan=PLAN),
                             objective="o", init=True)

    assert report.cost is None


def test_to_dict_shape_dry_run_without_cost(tmp_path):
    _repo(tmp_path)
    git.init_baseline(tmp_path)

    report = develop_feature(tmp_path, client=FakeClient(GOOD, plan=PLAN),
                             objective="o", dry_run=True)
    d = report.to_dict()

    assert d["schema_version"] == 2
    assert d["ok"] == report.project_ok
    assert d["objective"] == "o"
    assert d["dry_run"] is True
    assert isinstance(d["diff"], str) and "USE = VALUE" in d["diff"]
    assert d["cost"] is None
    assert set(d["verify_steps"]) <= {"compile", "ruff", "pytest", "bandit"}
    assert {"created", "modified", "deleted", "flagged", "unsafe"} <= set(d)
    assert "security_issues" in d


def test_to_dict_cost_dict_has_eight_keys(tmp_path):
    _repo(tmp_path)
    client = CostClient(GOOD, plan=PLAN)

    report = develop_feature(tmp_path, client=client, objective="o", init=True)
    cost = report.to_dict()["cost"]

    assert cost is not None
    assert set(cost) == {
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "cost_usd",
        "pricing_known",
        "cache_hit_ratio",
        "calls",
    }


def test_to_dict_live_run_diff_is_none(tmp_path):
    _repo(tmp_path)

    report = develop_feature(tmp_path, client=FakeClient(GOOD, plan=PLAN),
                             objective="o", init=True)
    d = report.to_dict()

    assert d["dry_run"] is False
    assert d["diff"] is None


def test_emits_file_retry_on_persistent_failure(tmp_path):
    (tmp_path / "bad.py").write_text("x = 1\n", encoding="utf-8")
    plan = ExecutionPlan(
        objective="o",
        steps=[PlanStep(path="bad.py", action="modify", instructions="break")],
    )
    client = FakeClient({"bad.py": "def (:\n"}, plan=plan)
    reporter = RecordingReporter()

    report = develop_feature(tmp_path, client=client, objective="o", init=True,
                             max_retries=3, on_event=reporter)

    retries = reporter.of_type(events.FileRetry)
    assert retries
    assert all(r.path == "bad.py" for r in retries)
    assert min(r.attempt for r in retries) >= 1

    flagged = [fd for fd in reporter.of_type(events.FileDone) if not fd.ok]
    assert any(fd.path == "bad.py" for fd in flagged)
    assert "bad.py" in report.flagged


# ---------------------------------------------------------------------------
# Security gate (per-step blocking SAST + Red Team audit)
# ---------------------------------------------------------------------------


def _one_step_repo(tmp_path, path="a.py", src="VALUE = 1\n"):
    (tmp_path / path).write_text(src, encoding="utf-8")
    return ExecutionPlan(
        objective="o",
        steps=[PlanStep(path=path, action="modify", instructions="touch")],
    )


def _block(issue="SQL injection via string concatenation"):
    return SecurityReview(
        ok=False,
        findings=[SecurityFinding(file="a.py", severity="high", issue=issue)],
    )


def test_security_gate_blocks_then_coder_fixes(tmp_path):
    plan = _one_step_repo(tmp_path)
    # First audit blocks; second passes -> accepted after one security retry.
    client = FakeClient(
        {"a.py": "VALUE = 2\n"}, plan=plan,
        security=[_block(), SecurityReview(ok=True)],
    )
    reporter = RecordingReporter()

    report = develop_feature(tmp_path, client=client, objective="o", init=True,
                             on_event=reporter)

    assert len(client.audit_calls) == 2  # blocked once, re-audited once
    rejects = reporter.of_type(events.SecurityReject)
    assert len(rejects) == 1 and rejects[0].path == "a.py" and rejects[0].attempt == 1
    assert rejects[0].issues  # the vulnerability was reported to the Coder
    assert "a.py" in report.modified and "a.py" not in report.unsafe
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert report.project_ok is True, report.project_errors


def test_security_gate_discards_unsafe_after_retries(tmp_path):
    plan = _one_step_repo(tmp_path, src="VALUE = 1\n")
    client = FakeClient({"a.py": "VALUE = 2\n"}, plan=plan, security=_block())
    reporter = RecordingReporter()

    report = develop_feature(tmp_path, client=client, objective="o", init=True,
                             max_retries=2, on_event=reporter)

    # Rejected every attempt, then discarded — nothing written for the unsafe file.
    assert len(reporter.of_type(events.SecurityReject)) == 2
    assert "a.py" in report.unsafe
    assert "a.py" not in report.modified
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "VALUE = 1\n"  # original kept
    git.require_clean_tree(tmp_path)  # the discarded candidate was never committed
    assert report.project_ok is True  # original (safe) code still verifies
    d = report.to_dict()
    assert d["unsafe"] == ["a.py"]


def test_security_gate_off_skips_audit(tmp_path):
    plan = _one_step_repo(tmp_path)
    client = FakeClient({"a.py": "VALUE = 2\n"}, plan=plan, security=_block())

    report = develop_feature(tmp_path, client=client, objective="o", init=True,
                             security_gate=False)

    assert client.audit_calls == []  # no Red Team calls when the gate is off
    assert "a.py" in report.modified  # would-be-blocked code is accepted
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "VALUE = 2\n"


def test_low_confidence_sast_injects_review_marker(tmp_path, monkeypatch):
    import claudebackend.orchestrator as orch

    plan = _one_step_repo(tmp_path)
    # A low-confidence/low-severity SAST warning the Red Team does not confirm:
    # not blocking, but it earns a CLAUDEBACKEND-REVIEW marker on accept.
    monkeypatch.setattr(
        orch, "scan_code",
        lambda code, driver=None: [SastFinding("B101", "LOW", "LOW", 1, "assert used")],
    )
    client = FakeClient({"a.py": "VALUE = 2\n"}, plan=plan)  # audit passes clean

    report = develop_feature(tmp_path, client=client, objective="o", init=True)

    assert "a.py" in report.modified and "a.py" not in report.unsafe
    written = (tmp_path / "a.py").read_text(encoding="utf-8")
    assert "CLAUDEBACKEND-REVIEW" in written
    assert "B101" in written
    assert "a.py" in report.review
