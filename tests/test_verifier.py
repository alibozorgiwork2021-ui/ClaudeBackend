import claudebackend.core.verifier as verifier
from claudebackend.core.verifier import (
    SastFinding,
    _parse_bandit_json,
    _parse_pytest_summary,
    _run_sast_check,
    bandit_available,
    format_sast,
    scan_code,
    verify_file,
    verify_project,
)


def _write(p, text):
    p.write_text(text, encoding="utf-8")


# --- verify_file: syntax gate only (D2) ---


def test_verify_file_pass(tmp_path):
    f = tmp_path / "ok.py"
    _write(f, "x = 1\nprint(x)\n")
    r = verify_file(f)
    assert r.ok is True
    assert r.errors == []


def test_verify_file_fail_on_py2(tmp_path):
    f = tmp_path / "bad.py"
    _write(f, 'print "hi"\n')
    r = verify_file(f)
    assert r.ok is False
    assert any("bad.py" in e for e in r.errors)


# --- verify_project: compileall + ruff(E9,F) + pytest is the real gate ---


def test_verify_project_passes_clean(tmp_path):
    _write(tmp_path / "mathutils.py", "def halve(n):\n    return n // 2\n")
    _write(
        tmp_path / "test_m.py",
        "from mathutils import halve\n\n\ndef test_h():\n    assert halve(6) == 3\n",
    )
    r = verify_project(tmp_path)
    assert r.ok is True, r.errors


def test_verify_project_ruff_flags_undefined_name(tmp_path):
    _write(tmp_path / "u.py", "def f():\n    return xrange(3)\n")
    r = verify_project(tmp_path)
    assert r.ok is False
    assert any("xrange" in e or "F821" in e for e in r.errors)


def test_verify_project_pytest_catches_failure(tmp_path):
    _write(tmp_path / "m.py", "def val():\n    return 1\n")
    _write(
        tmp_path / "test_m.py",
        "from m import val\n\n\ndef test_v():\n    assert val() == 2\n",
    )
    r = verify_project(tmp_path)
    assert r.ok is False
    assert any("pytest" in e.lower() for e in r.errors)


def test_verify_project_skips_pytest_when_no_tests(tmp_path):
    _write(tmp_path / "lib.py", "def f():\n    return 1\n")
    r = verify_project(tmp_path)
    assert r.ok is True
    assert any("no test" in n.lower() for n in r.notes)


# --- steps dict tests ---


def test_steps_clean_project_with_passing_tests(tmp_path):
    _write(tmp_path / "mathutils.py", "def halve(n):\n    return n // 2\n")
    _write(
        tmp_path / "test_m.py",
        "from mathutils import halve\n\n\ndef test_h():\n    assert halve(6) == 3\n",
    )
    r = verify_project(tmp_path)
    assert r.ok is True, r.errors
    assert r.steps["compile"] == "ok"
    assert r.steps["ruff"] == "ok"
    assert "passed" in r.steps["pytest"]


def test_steps_no_test_files(tmp_path):
    _write(tmp_path / "lib.py", "def f():\n    return 1\n")
    r = verify_project(tmp_path)
    assert r.steps["compile"] == "ok"
    assert r.steps["ruff"] == "ok"
    assert r.steps["pytest"] == "skipped"


def test_steps_ruff_failure(tmp_path):
    _write(tmp_path / "u.py", "def f():\n    return xrange(3)\n")
    r = verify_project(tmp_path)
    assert r.ok is False
    assert r.steps["ruff"] == "FAILED"
    assert any("xrange" in e or "F821" in e for e in r.errors)


def test_steps_compile_failure(tmp_path):
    _write(tmp_path / "bad.py", 'print "hi"\n')
    r = verify_project(tmp_path)
    assert r.ok is False
    assert r.steps["compile"] == "FAILED"


# --- _parse_pytest_summary: long runs append a wall-clock paren ---


def test_parse_pytest_summary_long_run_with_wallclock():
    # For suites >= 60s pytest appends a (H:MM:SS) suffix after the seconds.
    out = "...\n100 passed in 75.0s (0:01:15)"
    assert _parse_pytest_summary(out) == "100 passed"


# --- SAST (bandit) ---

_BANDIT_JSON = """
{"results": [
  {"test_id": "B608", "issue_severity": "HIGH", "issue_confidence": "MEDIUM",
   "line_number": 12, "issue_text": "Possible SQL injection"},
  {"test_id": "B101", "issue_severity": "LOW", "issue_confidence": "LOW",
   "line_number": 3, "issue_text": "assert used"}
]}
"""


def test_parse_bandit_json_extracts_findings():
    findings = _parse_bandit_json(_BANDIT_JSON)
    assert len(findings) == 2
    f = findings[0]
    assert isinstance(f, SastFinding)
    assert f.test_id == "B608"
    assert f.severity == "HIGH" and f.confidence == "MEDIUM"
    assert f.line == 12
    assert "SQL injection" in f.text


def test_parse_bandit_json_tolerates_junk():
    assert _parse_bandit_json("not json") == []
    assert _parse_bandit_json("") == []


def test_format_sast_renders_strings():
    out = format_sast([SastFinding("B608", "HIGH", "MEDIUM", 12, "sql")])
    assert out == ["B608 [HIGH/MEDIUM] line 12: sql"]


def test_run_sast_check_graceful_when_bandit_absent(tmp_path):
    if bandit_available():
        import pytest
        pytest.skip("bandit is installed in this environment")
    f = tmp_path / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    assert _run_sast_check(f) == []  # degrades to no findings, never raises


def test_scan_code_never_raises_and_returns_list():
    out = scan_code("import os\nos.system('x')\n")
    assert isinstance(out, list)  # [] when bandit absent; findings when present


def test_verify_project_records_bandit_step(tmp_path):
    _write(tmp_path / "lib.py", "def f():\n    return 1\n")
    r = verify_project(tmp_path)
    assert "bandit" in r.steps
    if not bandit_available():
        assert r.steps["bandit"] == "skipped"
        assert any("bandit" in n.lower() for n in r.notes)


def test_verify_project_surfaces_sast_advisory(tmp_path, monkeypatch):
    _write(tmp_path / "m.py", "def f():\n    return 1\n")
    monkeypatch.setattr(verifier, "bandit_available", lambda: True)
    monkeypatch.setattr(
        verifier, "_run_sast_check",
        lambda target: [SastFinding("B608", "HIGH", "HIGH", 2, "sql injection")],
    )

    r = verify_project(tmp_path)

    assert r.ok is True  # SAST is advisory at the project level — never fails ok
    assert r.steps["bandit"] == "1 issue(s)"
    assert any("B608" in s for s in r.security_issues)
