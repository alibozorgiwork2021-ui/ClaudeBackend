from claudebackend.agents.security_auditor import audit
from claudebackend.models import PlanStep, SecurityFinding, SecurityReview

STEP = PlanStep(path="api.py", action="modify", instructions="add an endpoint")


class _Client:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def parse(self, messages, output_model, model=None):
        self.calls.append(
            {"messages": messages, "output_model": output_model, "model": model}
        )
        return self.result


def test_empty_code_returns_ok_without_calling():
    c = _Client(None)
    out = audit(c, STEP, "   \n")
    assert isinstance(out, SecurityReview)
    assert out.ok and not out.findings
    assert c.calls == []  # no LLM call when there is nothing to audit


def test_audits_code_routes_model_and_returns_review():
    result = SecurityReview(
        ok=False,
        findings=[SecurityFinding(file="api.py", severity="high", issue="SQLi")],
    )
    c = _Client(result)

    out = audit(
        c, STEP, "q = 'SELECT * FROM t WHERE n=' + name",
        sast_findings=["B608 [HIGH/HIGH] line 1: possible SQL injection"],
        model="deep-model",
    )

    assert out is result
    assert c.calls[0]["model"] == "deep-model"
    assert c.calls[0]["output_model"] is SecurityReview
    content = c.calls[0]["messages"][0]["content"]
    assert "api.py" in content
    assert "attacker" in content.lower() or "red team" in content.lower()
    assert "B608" in content  # the SAST findings are handed to the Red Team
