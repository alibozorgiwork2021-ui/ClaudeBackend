from claudebackend.agents.security_reviewer import review
from claudebackend.models import SecurityFinding, SecurityReview


class _Client:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def parse(self, messages, output_model, model=None):
        self.calls.append(
            {"messages": messages, "output_model": output_model, "model": model}
        )
        return self.result


def test_empty_files_returns_ok_without_calling():
    c = _Client(None)
    out = review(c, {})
    assert isinstance(out, SecurityReview)
    assert out.ok and not out.findings
    assert c.calls == []  # no LLM call when there is nothing to review


def test_reviews_files_and_routes_model():
    result = SecurityReview(
        ok=False,
        findings=[SecurityFinding(file="a.py", severity="high", issue="raw SQL")],
    )
    c = _Client(result)
    out = review(c, {"a.py": "q = 'SELECT ' + name"}, model="deepseek-coder-v2")
    assert out is result
    assert c.calls[0]["model"] == "deepseek-coder-v2"
    assert c.calls[0]["output_model"] is SecurityReview
    assert "a.py" in c.calls[0]["messages"][0]["content"]


def test_skips_empty_sources():
    c = _Client(SecurityReview())
    review(c, {"a.py": "", "b.py": "import os"})
    content = c.calls[0]["messages"][0]["content"]
    assert "=== b.py ===" in content
    assert "=== a.py ===" not in content
