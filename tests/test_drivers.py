import pytest

from claudebackend.core.drivers import (
    PHPDriver,
    PythonDriver,
    detect_lang,
    get_driver,
)
from claudebackend.core.drivers.base import LanguageDriver, SyntaxCheck


def test_get_driver_python():
    d = get_driver("python")
    assert isinstance(d, PythonDriver)
    assert d.name == "python"


def test_get_driver_php():
    d = get_driver("php")
    assert isinstance(d, PHPDriver)
    assert d.name == "php"
    assert d.source_exts == (".php",)


def test_get_driver_is_cached():
    assert get_driver("php") is get_driver("php")


def test_get_driver_unknown_raises():
    with pytest.raises(ValueError) as exc:
        get_driver("ruby")
    msg = str(exc.value)
    assert "ruby" in msg and "php" in msg and "python" in msg


def test_detect_lang_composer(tmp_path):
    (tmp_path / "composer.json").write_text("{}", encoding="utf-8")
    assert detect_lang(tmp_path) == "php"


def test_detect_lang_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    assert detect_lang(tmp_path) == "python"


def test_detect_lang_requirements(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")
    assert detect_lang(tmp_path) == "python"


def test_detect_lang_php_source_majority(tmp_path):
    for n in ("a.php", "b.php", "c.php"):
        (tmp_path / n).write_text("<?php\n", encoding="utf-8")
    (tmp_path / "x.py").write_text("x = 1\n", encoding="utf-8")
    assert detect_lang(tmp_path) == "php"


def test_detect_lang_tie_defaults_python(tmp_path):
    (tmp_path / "a.php").write_text("<?php\n", encoding="utf-8")
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    assert detect_lang(tmp_path) == "python"


def test_detect_lang_empty_defaults_python(tmp_path):
    assert detect_lang(tmp_path) == "python"


def test_composer_beats_python_source(tmp_path):
    # Manifest wins over a stray .py file.
    (tmp_path / "composer.json").write_text("{}", encoding="utf-8")
    (tmp_path / "tool.py").write_text("x = 1\n", encoding="utf-8")
    assert detect_lang(tmp_path) == "php"


def test_abc_vuln_patterns_hint_default_empty():
    class Minimal(LanguageDriver):
        name = "min"
        source_exts = (".min",)

        def extract_imports(self, src):
            return set()

        def module_name(self, relpath):
            return relpath

        def resolve(self, mod, importer, modmap, relset):
            return None

        def verify_steps(self, root, target_version):
            return []

        def syntax_check(self, path):
            return SyntaxCheck(ok=True)

        def default_version(self):
            return "0"

    m = Minimal()
    assert m.vuln_patterns_hint() == ""
    assert m.scan_candidate("anything") == []


def test_python_vuln_patterns_hint():
    assert get_driver("python").vuln_patterns_hint() == "pickle/yaml.load/eval/exec"


def test_php_vuln_patterns_hint():
    hint = get_driver("php").vuln_patterns_hint()
    assert "unserialize" in hint and "eval" in hint


def test_comment_prefix():
    assert get_driver("python").comment_prefix() == "#"
    assert get_driver("php").comment_prefix() == "//"


def test_review_marker_line_uses_comment_syntax():
    assert (
        get_driver("python").review_marker_line("CLAUDEBACKEND-REVIEW", "why")
        == "# CLAUDEBACKEND-REVIEW: why"
    )
    assert (
        get_driver("php").review_marker_line("CLAUDEBACKEND-REVIEW", "why")
        == "// CLAUDEBACKEND-REVIEW: why"
    )


def test_python_scan_candidate_is_noop_default():
    # Python SAST is handled inline by verifier.scan_code (bandit), so the driver
    # method stays the ABC default.
    assert get_driver("python").scan_candidate("import os\nos.system('x')\n") == []
