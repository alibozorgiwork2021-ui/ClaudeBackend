"""End-to-end PHP pipeline tests: the orchestration is language-agnostic, so a
``FakeClient`` (no real LLM) drives a full run over a ``.php`` repo via the PHP
driver. These run without a PHP toolchain installed — the deterministic regex SAST
and the syntax gate degrade gracefully, so the security-gate behaviour is exercised
the same way on every machine.
"""

import shutil
from pathlib import Path

from claudebackend.core import git
from claudebackend.core.verifier import SastFinding
from claudebackend.models import (
    ExecutionPlan,
    PlanStep,
    SecurityFinding,
    SecurityReview,
)
from claudebackend.orchestrator import develop_feature

_FIXTURE = Path(__file__).parent / "fixtures" / "php_sample"


class FakeClient:
    """Type-aware fake: returns the plan for an ExecutionPlan request and a
    SecurityReview for the Red Team audit; maps each target path to canned code."""

    def __init__(self, outputs, plan=None, security=None):
        self.outputs = outputs
        self.plan = plan or ExecutionPlan(objective="o", steps=[])
        self.security = security
        self.audit_calls = []

    def estimate_tokens(self, messages):
        return 10

    def parse(self, messages, output_model, model=None):
        if output_model is SecurityReview:
            self.audit_calls.append(messages)
            if self.security is None:
                return SecurityReview(ok=True)
            return self.security
        return self.plan

    def stream_text(self, messages, system=None, model=None):
        text = "\n".join(b["text"] for b in messages[0]["content"])
        for path, code in self.outputs.items():
            if f"=== {path} ===" in text:
                return code, "end_turn"
        raise AssertionError(f"no canned output matched:\n{text}")


def _php_repo(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(_FIXTURE, repo)
    return repo


def test_php_safe_edit_reports_lang_and_modifies(tmp_path):
    repo = _php_repo(tmp_path)
    plan = ExecutionPlan(
        objective="o",
        steps=[PlanStep(path="src/Foo.php", action="modify", instructions="add id()")],
    )
    safe = (
        "<?php\n\nnamespace Acme;\n\nclass Foo\n{\n"
        "    public function id(): int\n    {\n        return 1;\n    }\n}\n"
    )
    client = FakeClient({"src/Foo.php": safe}, plan=plan)

    report = develop_feature(repo, client=client, objective="o", init=True, lang="php")

    assert report.lang == "php"
    assert "src/Foo.php" in report.modified
    assert report.project_ok is True, report.project_errors
    assert report.to_dict()["lang"] == "php"


def test_php_auto_detect_picks_php_from_composer(tmp_path):
    # The CLI/MCP "auto" path resolves the language via detect_lang; confirm the
    # composer.json fixture is detected as php.
    from claudebackend.core.drivers import detect_lang

    assert detect_lang(_php_repo(tmp_path)) == "php"


def test_php_security_gate_discards_unsafe_get_concat(tmp_path):
    repo = _php_repo(tmp_path)
    plan = ExecutionPlan(
        objective="o",
        steps=[PlanStep(path="src/Unsafe.php", action="create",
                        instructions="look a user up by id")],
    )
    unsafe = (
        "<?php\n\nnamespace Acme;\n\n"
        "function lookup($pdo)\n{\n"
        "    $q = \"SELECT * FROM users WHERE id=\" . $_GET['id'];\n"
        "    return $pdo->query($q);\n}\n"
    )
    # The Red Team also blocks (mirrors the deterministic PHP-SQLI finding).
    block = SecurityReview(
        ok=False,
        findings=[SecurityFinding(
            file="src/Unsafe.php", severity="high", issue="SQL injection via $_GET"
        )],
    )
    client = FakeClient({"src/Unsafe.php": unsafe}, plan=plan, security=block)

    report = develop_feature(
        repo, client=client, objective="o", init=True, lang="php", max_retries=2
    )

    # Unfixable within the retry budget -> discarded, nothing written.
    assert "src/Unsafe.php" in report.unsafe
    assert "src/Unsafe.php" not in report.created
    assert not (repo / "src" / "Unsafe.php").exists()
    git.require_clean_tree(repo)  # the discarded candidate was never committed


def test_php_review_marker_uses_php_comment_syntax(tmp_path, monkeypatch):
    import claudebackend.orchestrator as orch

    repo = _php_repo(tmp_path)
    plan = ExecutionPlan(
        objective="o",
        steps=[PlanStep(path="src/Foo.php", action="modify", instructions="touch")],
    )
    safe = "<?php\n\nnamespace Acme;\n\nclass Foo {}\n"
    # A low-confidence finding the Red Team does not confirm -> review marker (not a block).
    monkeypatch.setattr(
        orch, "scan_code",
        lambda code, driver=None: [
            SastFinding("PHP-XSS", "MEDIUM", "LOW", 1, "echo of request data")
        ],
    )
    client = FakeClient({"src/Foo.php": safe}, plan=plan)  # audit passes clean

    report = develop_feature(repo, client=client, objective="o", init=True, lang="php")

    assert "src/Foo.php" in report.modified
    written = (repo / "src" / "Foo.php").read_text(encoding="utf-8")
    assert "// CLAUDEBACKEND-REVIEW" in written  # PHP comment syntax, not "#"
    assert "PHP-XSS" in written
    assert "src/Foo.php" in report.review
