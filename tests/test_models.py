import pytest
from pydantic import ValidationError

from claudebackend.models import ExecutionPlan, FileResult, PlanStep, VerifyResult


def test_verify_result_round_trip():
    vr = VerifyResult(ok=False, errors=["boom"])
    assert vr.ok is False
    assert vr.errors == ["boom"]
    assert VerifyResult.model_validate(vr.model_dump()) == vr


def test_verify_result_defaults_to_ok_empty_errors():
    vr = VerifyResult(ok=True)
    assert vr.errors == []


def test_verify_result_security_issues_default_empty():
    vr = VerifyResult(ok=True)
    assert vr.security_issues == []
    vr2 = VerifyResult(ok=True, security_issues=["B608 line 3: sql"])
    assert vr2.security_issues == ["B608 line 3: sql"]


def test_file_result_notes_default_empty():
    fr = FileResult(path="a.py", code="print('x')")
    assert fr.notes == ""
    assert fr.code == "print('x')"


def test_plan_step_rejects_bad_risk():
    with pytest.raises(ValidationError):
        PlanStep(path="a.py", action="modify", instructions="x", risk="extreme")


def test_plan_step_rejects_bad_action():
    with pytest.raises(ValidationError):
        PlanStep(path="a.py", action="rename", instructions="x")


def test_plan_step_defaults():
    step = PlanStep(path="a.py", action="create", instructions="make it")
    assert step.risk == "low"
    assert step.rationale == ""
    assert step.depends_on == []


def test_execution_plan_round_trip():
    plan = ExecutionPlan(
        objective="Add a health endpoint",
        summary="approach",
        steps=[
            PlanStep(path="health.py", action="create", instructions="add health()"),
            PlanStep(
                path="app.py", action="modify", instructions="wire it",
                depends_on=["health.py"], risk="medium",
            ),
        ],
    )
    assert ExecutionPlan.model_validate(plan.model_dump()) == plan
    assert plan.steps[1].depends_on == ["health.py"]
